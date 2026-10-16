"""
speech.py - slides JSON -> humanized, explainable narration per slide.

python speech.py slides.json --out speech.json
python speech.py slides.json --format txt --out speech.txt
python speech.py --paragraph "<paragraph>" --out speech.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def _get_cf_config() -> tuple[str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not account_id.strip():
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is missing or empty in your .env file.")
    if not api_token or not api_token.strip():
        raise ValueError("CLOUDFLARE_API_TOKEN is missing or empty in your .env file.")
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id.strip()}/ai/v1", api_token.strip()
SPEECH_PROMPT = """You are a friendly teacher narrating one slide of a presentation out loud.

RULES:
1. Write natural spoken English: conversational, warm, easy to follow. No markdown, no bullet symbols, no emojis, no stage directions.
2. Cover EVERY item on the slide (all list items, table rows, terms and full forms). Do not skip any.
3. Explain in plain words what the content means, so a beginner understands. You may rephrase and clarify, but do NOT add facts, numbers or claims that are not in the slide.
4. For lists, weave the items into flowing sentences. For tables, walk through each row naturally (e.g. "DDL stands for ... and it is used for ...").
5. Keep it 3-6 sentences, about 40-110 words.
6. Use a short natural transition from the previous slide if one is given. Do not say "slide number".
7. Output ONLY the narration text."""

INTRO_PROMPT = """You are a friendly teacher opening a presentation. Write a 2-3 sentence spoken introduction
for the topic below and mention what the viewer will learn, using only the agenda given.
Plain spoken English, no markdown. Output ONLY the narration text."""


def _client() -> OpenAI:
    base_url, token = _get_cf_config()
    return OpenAI(base_url=base_url, api_key=token, timeout=60.0)


def _describe(s: dict[str, Any]) -> str:
    parts = [f"Layout: {s['layout']}", f"Heading: {s.get('heading', '')}"]
    if s.get("text"):
        parts.append(f"Text: {s['text']}")
    if s.get("points"):
        parts.append("Points: " + "; ".join(s["points"]))
    t = s.get("table")
    if t:
        parts.append("Table columns: " + " | ".join(t["columns"]))
        for r in t["rows"]:
            parts.append("Row: " + " | ".join(r))
    f = s.get("formula")
    if f:
        parts.append(f"Formula: {f['equation']}")
        for k, v in (f.get("variables") or {}).items():
            parts.append(f"Variable {k}: {v}")
    if s.get("source_text"):
        parts.append(f"Original sentence: {s['source_text']}")
    return "\n".join(parts)


def _fallback(s: dict[str, Any]) -> str:
    """Used only if the API call fails, so the output order is never broken."""
    out = [s.get("text") or s.get("heading", "")]
    if s.get("points"):
        out.append("These are " + ", ".join(s["points"][:-1]) + (" and " if len(s["points"]) > 1 else "") + s["points"][-1] + ".")
    if s.get("table"):
        cols = s["table"]["columns"]
        for r in s["table"]["rows"]:
            out.append(f"{r[0]}: " + ", ".join(f"{c.lower()} {v}" for c, v in zip(cols[1:], r[1:])) + ".")
    return " ".join(x for x in out if x)


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-\u2022]\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip().strip('"')


def _ask(client: OpenAI, model: str, system: str, user: str) -> str:
    c = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
        max_tokens=600,
        stream=False,
    )
    return _clean(c.choices[0].message.content or "")


def generate_speech(deck: dict[str, Any], model: str = DEFAULT_MODEL, cover: bool = True) -> dict[str, Any]:
    client = _client()
    slides = deck.get("slides", [])
    title = deck.get("deck_title", "")
    out: list[dict[str, Any]] = []

    if cover:
        agenda = ", ".join(s.get("heading", "") for s in slides if s.get("heading"))
        try:
            intro = _ask(client, model, INTRO_PROMPT, f"Topic: {title}\nAgenda: {agenda}")
        except Exception as e:
            sys.stderr.write(f"[cover] API error: {e}\n")
            intro = ""
        out.append({"slide_number": 0, "heading": title, "speech": intro or f"Welcome. Today we will talk about {title}."})

    prev = ""
    for i, s in enumerate(slides):
        last = i == len(slides) - 1
        user = (
            f"Presentation topic: {title}\n"
            f"Previous slide heading: {prev or 'none (this is the first content slide)'}\n"
            f"This is the last slide: {'yes, end with a brief natural wrap-up' if last else 'no'}\n\n"
            f"SLIDE:\n{_describe(s)}"
        )
        try:
            speech = _ask(client, model, SPEECH_PROMPT, user)
        except Exception as e:
            sys.stderr.write(f"[slide {s.get('slide_number')}] API error: {e}\n")
            speech = ""
        out.append({
            "slide_number": s["slide_number"],
            "heading": s.get("heading", ""),
            "speech": speech or _fallback(s),
        })
        prev = s.get("heading", "")

    return {"deck_title": title, "slides": out}


def to_text(speech: dict[str, Any]) -> str:
    blocks = []
    for s in speech["slides"]:
        label = "Cover" if s["slide_number"] == 0 else f"Slide {s['slide_number']}"
        blocks.append(f"[{label}] {s['heading']}\n{s['speech']}")
    return "\n\n".join(blocks)


def load_deck(path: str) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    raw = re.sub(r"```(?:json)?", "", raw).strip()  # tolerate pasted code fences
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser(description="Slides JSON -> narration per slide")
    ap.add_argument("json_file", nargs="?", help="slides-json file (or pipe via stdin)")
    ap.add_argument("--paragraph", help="Run the search_structure pipeline on this paragraph first")
    ap.add_argument("--format", default="json", choices=["json", "txt"])
    ap.add_argument("--out", help="Output file (prints to console if omitted)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-cover", action="store_true", help="Skip the cover/intro narration")
    args = ap.parse_args()

    if args.paragraph:
        from search_structure import structure_paragraph_sync, structure_to_slides
        deck = structure_to_slides(structure_paragraph_sync(args.paragraph, model=args.model))
    elif args.json_file:
        deck = load_deck(args.json_file)
    elif not sys.stdin.isatty():
        deck = json.loads(re.sub(r"```(?:json)?", "", sys.stdin.read()).strip())
    else:
        ap.print_help()
        sys.exit(1)

    speech = generate_speech(deck, model=args.model, cover=not args.no_cover)
    output = to_text(speech) if args.format == "txt" else json.dumps(speech, indent=2, ensure_ascii=False)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Saved {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()