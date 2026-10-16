"""
start_query.py - search-bar query -> one factual paragraph for search_structure.py.

python start_query.py "SQL"
python start_query.py "what is photosynthesis" --sentences 6 --out paragraph.txt
python start_query.py "Newton's laws" --lang en

Needs .env with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.

Backend (backend/main.py):
  sys.path.insert(0, str(SRC / "start_pro"))
  import start_query
  app.include_router(start_query.router)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
MIN_SENTENCES, MAX_SENTENCES = 3, 8
PASSTHROUGH_WORDS = 60  # a query this long with 3+ sentences is already a paragraph
MATH_TERMS = re.compile(
    r"\b("
    r"algebra|angle|area|arithmetic|calculus|calculate|circumference|compute|derive|"
    r"derivative|differentiate|equation|evaluate|factor|fraction|geometry|inequality|"
    r"integral|integrate|matrix|mathematics|math|median|perimeter|percentage|polynomial|"
    r"probability|proof|quadratic|radius|simplify|slope|solve|statistics|theorem|"
    r"trigonometry|variable|volume"
    r")\b",
    re.IGNORECASE,
)
MATH_EXPRESSION = re.compile(r"\d\s*(?:[+\-*/^=<>]|×|÷)\s*\d|[a-zA-Z]\s*=\s*-?\d")
COMPARISON_QUESTION = re.compile(
    r"\b(?:compare|comparison|contrast|differences?|distinguish|similarities|versus|vs\.?)\b"
    r"|\bhow\s+(?:does|do|is|are)\b.{1,100}\bdiffer(?:s|ent)?\b"
    r"|\bwhat\s+(?:is|are)\s+the\s+differences?\s+between\b",
    re.IGNORECASE,
)

PROMPT = """You write a factual, topic-specific study explanation for a slide generator.
Answer the user's exact topic or question, and choose the content and amount of detail that fit it.

RULES:
1. Write one coherent paragraph, without headings, bullets, markdown, or emojis.
2. Focus on the most relevant ideas for this topic. Do not force a generic sequence such as definition, uses, types, operations, and importance; include those only when they genuinely help answer this query.
3. Adapt to the kind of question: explain causes for "why", steps for "how", contrasts for comparisons, chronology for historical topics, and the requested scope for specific questions.
4. Use enough distinct factual ideas to support a short slide deck. Keep a simple topic concise and give a broad or complex topic more coverage; normally use about 4-12 clear sentences, with one main idea per sentence.
5. Use only well-established facts. Do not invent numbers, dates, names, or claims. If unsure, leave it out.
6. Use plain, simple English. No first person, rhetorical questions, or mention of these instructions.
7. Output ONLY the paragraph."""

MATH_PROMPT = """This is a mathematics question.
Answer the exact problem, not just the general topic. For a solve, calculate, simplify, or proof request, show the actual result through ordered, explicit steps; write each important equation/transformation in readable plain-text notation and clearly state the final answer. Check the result when practical. Do not skip straight to the answer or substitute a generic overview.
For a mathematical concept question, explain the relevant equation and define its variables when they help answer the question. Never invent givens, and say when the provided information is insufficient."""


def is_math_question(query: str) -> bool:
    """Return whether the question asks for mathematical reasoning or an equation."""
    return bool(MATH_TERMS.search(query) or MATH_EXPRESSION.search(query))


def is_comparison_question(query: str) -> bool:
    """Return whether the question asks to compare, contrast, or distinguish things."""
    return bool(COMPARISON_QUESTION.search(query))


def _get_cf_config() -> tuple[str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not account_id.strip():
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is missing or empty in your .env file.")
    if not api_token or not api_token.strip():
        raise ValueError("CLOUDFLARE_API_TOKEN is missing or empty in your .env file.")
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id.strip()}/ai/v1", api_token.strip()


def _clean_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "")).strip().strip('"\'')


def _clean_paragraph(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*(?:#+|[-*\u2022]|\d+[.)])\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"^(?:here(?:'s| is)[^:]*:|paragraph:)\s*", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().strip('"')


def _count_sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()])


def _looks_like_paragraph(q: str) -> bool:
    return len(q.split()) >= PASSTHROUGH_WORDS and _count_sentences(q) >= 3


def query_to_paragraph(
    query: str,
    sentences: Optional[int] = None,
    model: str = DEFAULT_MODEL,
    lang: str = "en",
) -> str:
    """Importable. Returns one paragraph ready for search_structure.structure_paragraph_sync()."""
    query = _clean_query(query)
    if not query:
        raise ValueError("Please enter a topic or question.")
    if len(query) > 4000:
        raise ValueError("Query is too long (max 4000 characters).")
    if _looks_like_paragraph(query):
        return query  # user already pasted a paragraph

    base_url, token = _get_cf_config()
    client = OpenAI(base_url=base_url, api_key=token, timeout=60.0)

    system = PROMPT
    if is_math_question(query):
        system += "\n" + MATH_PROMPT
    if sentences is not None:
        sentences = max(MIN_SENTENCES, min(MAX_SENTENCES, sentences))
        system += f"\nWrite exactly {sentences} sentences."
    if lang != "en":
        system += f"\nWrite the paragraph in the language with code '{lang}'."

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            c = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Topic or question: {query}"},
                ],
                temperature=0.3,
                max_tokens=700,
                stream=False,
            )
            para = _clean_paragraph(c.choices[0].message.content or "")
            if para and _count_sentences(para) >= 2:
                return para
            last_err = ValueError("model returned an unusable paragraph")
        except Exception as e:
            last_err = e
            sys.stderr.write(f"[query] attempt {attempt + 1}: {type(e).__name__}: {e}\n")
    raise RuntimeError(f"Could not generate a paragraph: {last_err}")


# ----------------------------------------------------------------------
# FastAPI router (search bar -> paragraph, optionally -> slides)
# ----------------------------------------------------------------------

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field

    router = APIRouter(prefix="/api", tags=["query"])

    class QueryReq(BaseModel):
        query: str = Field(min_length=1, max_length=4000)
        sentences: Optional[int] = None
        lang: str = "en"
        model: str = DEFAULT_MODEL

    @router.post("/query")
    def query(req: QueryReq) -> dict[str, Any]:
        """Search-bar text -> {query, paragraph}. Feed `paragraph` to /api/generate or /api/structure."""
        try:
            para = query_to_paragraph(req.query, req.sentences, req.model, req.lang)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        return {"query": _clean_query(req.query), "paragraph": para}

except ImportError:  # CLI works without fastapi installed
    router = None


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Search query -> paragraph for search_structure.py")
    ap.add_argument("query", nargs="?", help="Search text (or pipe via stdin)")
    ap.add_argument("--sentences", type=int, help=f"Request a specific count ({MIN_SENTENCES}-{MAX_SENTENCES}); default adapts to the topic")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, help="Write paragraph to this file")
    a = ap.parse_args()

    q = a.query if a.query else ("" if sys.stdin.isatty() else sys.stdin.read())
    if not q.strip():
        ap.print_help()
        sys.exit(1)

    try:
        para = query_to_paragraph(q, a.sentences, a.model, a.lang)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"[error] {e}")

    if a.out:
        a.out.write_text(para, encoding="utf-8")
        print(f"Saved {a.out}", file=sys.stderr)
    print(para)


if __name__ == "__main__":
    main()