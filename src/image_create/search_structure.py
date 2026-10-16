"""
Cloudflare Workers AI paragraph structurer -> content-sized, layout-tagged slides.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI, APIConnectionError, APITimeoutError, APIStatusError

load_dotenv()

DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
MAX_TOKENS = 4096

LAYOUTS = ["plain_text", "bullets", "process", "classification", "comparison", "formula", "example", "definition"]

SYSTEM_PROMPT = """You are an expert educator. Turn the input paragraph into an ordered, concise slide deck.

RULES:
1. Create 1-8 blocks, using only as many slides as the source material needs. A focused answer may need one slide; a broad or complex answer can have more.
2. Group related sentences into coherent subtopics instead of making one slide per sentence. Keep the ideas in a clear teaching order and cover the important points without repeating them.
3. Choose slide headings and content to fit this specific topic and question. Do not use a fixed outline or add generic definition, uses, types, operations, or importance slides unless the source supports them and they are relevant.
4. Never invent facts. Use only information present in supplied source prose; when given a topic or question directly, answer with reliable, well-established facts.
5. "source_text" = the source sentence(s) represented on that slide, quoted verbatim when source prose is provided.
6. Choose "layout" for each slide:
   - plain_text: ordinary statement. Put the sentence verbatim in "text".
   - definition: use only when this subtopic genuinely defines a term. Put the definition in "text".
   - classification: use only when the source actually lists types/categories/kinds. Fill "items" with one entry per type:
     {"term": "short name", "full_form": "full form/expansion if stated in the source, else empty string", "description": "what it does, from the source"}.
     Put any lead-in wording in "text".
   - bullets: related features, evidence, examples, causes, effects, or other useful points. Put a brief lead-in in "text" and each point in "points".
   - process: ordered steps or events. Put them in "points" in order.
   - comparison: use for every question that asks to compare, contrast, explain differences, or distinguish things. Put the comparison in a table with columns ["Aspect", "Subject A", "Subject B", ...] and rows [["criterion", "value for A", "value for B", ...], ...]. Each row MUST be an array with one complete cell value per column; never put a row in a plain string. Do not present the main comparison only as bullets or prose.
   - formula: use only when an equation is relevant. Fill "formula": {"equation": "...", "variables": {"x": "meaning"}}.
   - example: a concrete example or case study. Put it in "text".
7. When the source contains a math problem, preserve its equations exactly and put each algebraic transformation or calculation in its own ordered "points" entry. Put the final equation or result in "formula.equation"; do not turn a worked solution into a formula-only slide.
8. Output ONLY valid JSON in this schema (unused fields: "" / [] / null):

{
  "title": "concise title of the paragraph",
  "blocks": [
    {
      "source_text": "",
      "layout": "plain_text | definition | classification | bullets | process | comparison | formula | example",
      "heading": "2-5 word heading",
      "text": "",
      "points": [],
      "items": [{"term": "", "full_form": "", "description": ""}],
      "table": {"columns": ["Aspect", "Subject A", "Subject B"], "rows": [["criterion", "value for A", "value for B"]]},
      "say": "Concise, natural spoken narration that explains this slide.",
      "formula": null
    }
  ]
}"""


# ======================================================================
# API
# ======================================================================

def _get_cf_config() -> tuple[str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not account_id.strip():
        raise ValueError("\n[Error]: CLOUDFLARE_ACCOUNT_ID is missing or empty in your .env file.")
    if not api_token or not api_token.strip():
        raise ValueError("\n[Error]: CLOUDFLARE_API_TOKEN is missing or empty in your .env file.")
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id.strip()}/ai/v1", api_token.strip()


def _repair_truncated_json(s: str) -> str:
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        s += '"'
    s = re.sub(r",\s*$", "", s)
    return s + "".join(reversed(stack))


def _clean_json_response(content: str) -> dict[str, Any]:
    if not content:
        return {}
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = re.sub(r"```(?:json)?", "", content).strip()
    start = content.find("{")
    if start == -1:
        return {}
    raw = content[start:]
    end = raw.rfind("}")
    for candidate in (raw[: end + 1], _repair_truncated_json(raw[: end + 1]), _repair_truncated_json(raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    sys.stderr.write(f"\n[JSON Parse Error] Raw Output:\n{raw}\n")
    return {}


def _user_prompt(paragraph: str, query: str = "") -> str:
    context = f'Original user question:\n"""\n{query.strip()}\n"""\n\n' if query.strip() else ""
    return f'{context}Input Paragraph:\n"""\n{paragraph.strip()}\n"""\n'


def _messages(
    paragraph: str,
    lang: str = "en",
    query: str = "",
    math_question: bool = False,
    comparison_question: bool = False,
    direct_query: bool = False,
    narration_lang: str = "en",
) -> list[dict[str, str]]:
    system_prompt = SYSTEM_PROMPT
    if direct_query:
        system_prompt += (
            "\nThe input is the user's topic or question, not a supplied source paragraph. "
            "Answer it directly using reliable knowledge, then create the slides in this "
            "same response. Keep the answer focused and concise. Do not claim the user "
            "provided facts that are not present. Set source_text to a concise statement "
            "of the slide content, not a quotation. Every block must include a `say` "
            "field with concise, natural spoken narration covering its visible content."
        )
    if math_question:
        system_prompt += (
            "\nThis is a math question: answer the exact question, show all necessary "
            "work as ordered calculation steps, preserve equation notation, and clearly "
            "state the final answer. For a math concept question, explain its relevant "
            "equation and define variables rather than inventing a solve problem."
        )
    if comparison_question:
        system_prompt += (
            "\nThis is a comparison or difference question. The answer must include a "
            "comparison slide using a clearly labeled table. Use one column per subject "
            "and rows for the meaningful criteria or differences; include similarities "
            "when relevant. Do not replace the table with prose or bullets. Use only "
            "facts supported by the source paragraph."
        )
    if lang != "en":
        system_prompt += (
            f"\nWrite every generated heading, text, point, table value, and explanation "
            f"in the language with code '{lang}'. Keep the source_text verbatim."
        )
    if narration_lang == "hi":
        system_prompt += (
            "\nKeep all visible slide content in English. Write each block's `say` "
            "field in natural spoken Hindi using Devanagari; preserve technical terms "
            "and equations as written."
        )
    elif direct_query:
        system_prompt += "\nWrite each block's `say` in natural, concise spoken English."
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f'User topic or question:\n"""\n{query.strip() or paragraph.strip()}\n"""\n'
                if direct_query
                else _user_prompt(paragraph, query)
            ),
        },
    ]


def structure_paragraph_sync(
    paragraph: str,
    model: str = DEFAULT_MODEL,
    lang: str = "en",
    query: str = "",
    math_question: bool = False,
    comparison_question: bool = False,
    direct_query: bool = False,
    narration_lang: str = "en",
    **_: Any,
) -> dict[str, Any]:
    if not paragraph or not paragraph.strip():
        raise ValueError("Please provide a paragraph.")
    base_url, api_token = _get_cf_config()
    client = OpenAI(base_url=base_url, api_key=api_token, timeout=60.0)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=_messages(
                paragraph, lang, query, math_question, comparison_question,
                direct_query, narration_lang,
            ),
            temperature=0.1,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            stream=False,
        )
        return _clean_json_response(completion.choices[0].message.content or "")
    except APIStatusError as e:
        sys.stderr.write(f"\n[Cloudflare API Error {e.status_code}]: {e.message}\n")
        sys.exit(1)
    except APITimeoutError:
        sys.stderr.write("\n[Error]: Cloudflare API request timed out after 60 seconds.\n")
        sys.exit(1)
    except APIConnectionError as e:
        sys.stderr.write(f"\n[Connection Error]: {e}\n")
        sys.exit(1)


async def structure_paragraph(
    paragraph: str,
    model: str = DEFAULT_MODEL,
    lang: str = "en",
    query: str = "",
    math_question: bool = False,
    comparison_question: bool = False,
    direct_query: bool = False,
    narration_lang: str = "en",
    **_: Any,
) -> dict[str, Any]:
    if not paragraph or not paragraph.strip():
        raise ValueError("Please provide a paragraph.")
    base_url, api_token = _get_cf_config()
    client = AsyncOpenAI(base_url=base_url, api_key=api_token, timeout=60.0)
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=_messages(
                paragraph, lang, query, math_question, comparison_question,
                direct_query, narration_lang,
            ),
            temperature=0.1,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            stream=False,
        )
        return _clean_json_response(completion.choices[0].message.content or "")
    except APIStatusError as e:
        sys.stderr.write(f"\n[Cloudflare API Error {e.status_code}]: {e.message}\n")
        sys.exit(1)


# ======================================================================
# BLOCKS -> SLIDES  (one slide per source sentence, source order kept)
# ======================================================================

def _normalize_table(table: Any) -> dict[str, Any] | None:
    if not isinstance(table, dict):
        return None

    raw_columns = table.get("columns")
    if not isinstance(raw_columns, (list, tuple)) or not raw_columns:
        return None
    columns = [str(column) for column in raw_columns]
    raw_rows = table.get("rows") or []
    if isinstance(raw_rows, (str, dict)):
        raw_rows = [raw_rows]
    if not isinstance(raw_rows, (list, tuple)):
        return {"columns": columns, "rows": []}

    rows = []
    for row in raw_rows:
        if isinstance(row, dict):
            cells = [row.get(column, "") for column in columns]
        elif isinstance(row, (list, tuple)):
            cells = list(row)
        elif isinstance(row, str):
            delimiter = "\t" if "\t" in row else "|" if "|" in row else None
            cells = [cell.strip() for cell in row.split(delimiter)] if delimiter else [row]
        else:
            cells = [row]
        normalized = [str(cell) if cell is not None else "" for cell in cells[:len(columns)]]
        normalized.extend([""] * (len(columns) - len(normalized)))
        if any(cell.strip() for cell in normalized):
            rows.append(normalized)

    return {"columns": columns, "rows": rows}


def _block_to_slide(b: dict[str, Any], n: int) -> dict[str, Any]:
    layout = b.get("layout") if b.get("layout") in LAYOUTS else "plain_text"
    src = str(b.get("source_text") or "")
    text = str(b.get("text") or "")
    points = [str(p) for p in (b.get("points") or []) if p]
    items = [i for i in (b.get("items") or []) if isinstance(i, dict) and i.get("term")]

    table = _normalize_table(b.get("table"))

    formula = b.get("formula") if isinstance(b.get("formula"), dict) and b["formula"].get("equation") else None

    if layout == "classification":
        has_full = any(i.get("full_form") for i in items)
        cols = ["Term"] + (["Full Form"] if has_full else []) + ["Description"]
        rows = [
            [str(i["term"])] + ([str(i.get("full_form") or "")] if has_full else []) + [str(i.get("description") or "")]
            for i in items
        ]
        table = {"columns": cols, "rows": rows} if rows else None
        if not table:
            layout = "bullets" if points else "plain_text"

    if layout == "comparison" and not table:
        layout = "bullets" if points else "plain_text"
    if layout in ("bullets", "process") and not points:
        layout = "plain_text"
    if layout == "formula" and not formula:
        layout = "plain_text"
    if layout in ("plain_text", "definition", "example") and not text:
        text = src

    return {
        "slide_number": n,
        "layout": layout,
        "heading": str(b.get("heading") or ""),
        "text": text,
        "points": points,
        "numbered": layout == "process",
        "table": table,
        "say": str(b.get("say") or ""),
        "formula": formula,
        "source_text": src,
    }


def structure_to_slides(data: dict[str, Any]) -> dict[str, Any]:
    blocks = [b for b in (data or {}).get("blocks", []) if isinstance(b, dict)]
    slides = [_block_to_slide(b, i) for i, b in enumerate(blocks, 1)]
    return {"deck_title": (data or {}).get("title", ""), "slides": slides}


# ======================================================================
# RENDERERS
# ======================================================================

def _md_table(table: dict[str, Any]) -> list[str]:
    cols = table["columns"]
    out = ["", "| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in table["rows"]:
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in row]
        cells = (cells + [""] * len(cols))[: len(cols)]
        out.append("| " + " | ".join(cells) + " |")
    return out


def _slide_md(s: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if s["heading"]:
        out += [f"## {s['heading']}", ""]
    if s["text"]:
        out += [s["text"], ""]
    for n, p in enumerate(s["points"], 1):
        out.append(f"{n}. {p}" if s["numbered"] else f"- {p}")
    if s["table"]:
        out += _md_table(s["table"])
    if s["formula"]:
        out += ["", f"`{s['formula']['equation']}`", ""]
        for k, v in (s["formula"].get("variables") or {}).items():
            out.append(f"- `{k}`: {v}")
    return out


def slides_to_markdown(deck: dict[str, Any]) -> str:
    """Marp / reveal-md: slides separated by '---'."""
    if not deck["slides"]:
        return "Error: Unable to produce slides from API response."
    out = ["---", "marp: true", "paginate: true", "---", "", f"# {deck['deck_title']}"]
    for s in deck["slides"]:
        out += ["", "---", ""] + _slide_md(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def structure_to_markdown(data: dict[str, Any]) -> str:
    deck = structure_to_slides(data)
    if not deck["slides"]:
        return "Error: Unable to produce structure from API response."
    out = [f"# {deck['deck_title']}", ""]
    for s in deck["slides"]:
        out += _slide_md(s) + [""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def slides_to_pptx(deck: dict[str, Any], path: str) -> None:
    """pip install python-pptx"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()

    t = prs.slides.add_slide(prs.slide_layouts[0])
    t.shapes.title.text = deck["deck_title"] or "Presentation"
    t.placeholders[1].text = ""

    def add_table(slide, table):
        cols, rows = table["columns"], table["rows"]
        shape = slide.shapes.add_table(
            len(rows) + 1, len(cols), Inches(0.5), Inches(1.6), Inches(9), Inches(0.5) * (len(rows) + 1)
        )
        tbl = shape.table
        for c, name in enumerate(cols):
            tbl.cell(0, c).text = name
        for r, row in enumerate(rows, 1):
            for c in range(len(cols)):
                tbl.cell(r, c).text = row[c] if c < len(row) else ""
                tbl.cell(r, c).text_frame.paragraphs[0].font.size = Pt(14)

    for s in deck["slides"]:
        title = s["heading"] or deck["deck_title"]
        if s["table"]:
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = title
            add_table(slide, s["table"])
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = title
            tf = slide.placeholders[1].text_frame
            tf.clear()
            lines: list[str] = []
            if s["text"]:
                lines.append(s["text"])
            lines += [f"{n}. {p}" if s["numbered"] else f"\u2022 {p}" for n, p in enumerate(s["points"], 1)]
            if s["formula"]:
                lines.append(s["formula"]["equation"])
                lines += [f"{k}: {v}" for k, v in (s["formula"].get("variables") or {}).items()]
            for i, line in enumerate(lines):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = line
                p.font.size = Pt(24 if not s["points"] else 20)
        if s["source_text"]:
            slide.notes_slide.notes_text_frame.text = f"Source: {s['source_text']}"
    prs.save(path)


# ======================================================================
# CLI
# ======================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Cloudflare Workers AI Paragraph Structurer")
    parser.add_argument("paragraph", nargs="?", help="Paragraph text")
    parser.add_argument("--detail", default="detailed", help="(ignored, kept for compatibility)")
    parser.add_argument(
        "--format", default="slides-json",
        choices=["slides-json", "marp", "pptx", "markdown", "json"],
    )
    parser.add_argument("--out", help="Output file path (default output.pptx for pptx)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    text = args.paragraph if args.paragraph else sys.stdin.read()
    if not text.strip():
        parser.print_help()
        sys.exit(1)

    result = structure_paragraph_sync(text, model=args.model)
    deck = structure_to_slides(result)

    if args.format == "pptx":
        out_path = args.out or "output.pptx"
        slides_to_pptx(deck, out_path)
        print(f"Saved {out_path}")
        return

    if args.format == "json":
        output = json.dumps(result, indent=2, ensure_ascii=False)
    elif args.format == "slides-json":
        output = json.dumps(deck, indent=2, ensure_ascii=False)
    elif args.format == "marp":
        output = slides_to_markdown(deck)
    else:
        output = structure_to_markdown(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()