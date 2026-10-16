"""
htts.py - speech.json (English) -> Hindi translation -> Hindi MP3 per slide.

python htts.py speech.json --out audio_hi
python htts.py speech.json --out audio_hi --merge
python htts.py speech.json --slow
python htts.py speech.json --skip-translate     # input is already Hindi

pip install gTTS openai python-dotenv
Needs .env with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (translation step).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from gtts import gTTS
from gtts.tts import gTTSError
from openai import OpenAI
from requests.exceptions import RequestException

load_dotenv()

DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
TRANSLATE_PROMPT = """You are a professional English-to-Hindi translator for spoken teaching narration.

RULES:
1. Translate the text into natural, simple, conversational Hindi in Devanagari script, as a teacher would speak it.
2. Keep technical terms and acronyms (SQL, MySQL, PostgreSQL, Oracle, SQL Server, DDL, DML, DQL, DCL, TCL, etc.) in English letters exactly as written. Full forms may stay in English or be explained in Hindi.
3. Translate everything. Do not skip, add, or change any facts.
4. Plain text only: no markdown, no bullets, no emojis, no transliteration in brackets.
5. Output ONLY the Hindi translation."""


def _get_cf_config() -> tuple[str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not account_id.strip():
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is missing or empty in your .env file.")
    if not api_token or not api_token.strip():
        raise ValueError("CLOUDFLARE_API_TOKEN is missing or empty in your .env file.")
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id.strip()}/ai/v1", api_token.strip()


def load_speech(path: str) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    return json.loads(raw)


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip().strip('"')


def _has_devanagari(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text))


def translate(client: OpenAI, model: str, text: str) -> str:
    """English -> Hindi; retries up to 3 times and checks the result is actually Hindi."""
    for attempt in range(3):
        try:
            c = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": TRANSLATE_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                max_tokens=1200,
                stream=False,
            )
            out = _clean(c.choices[0].message.content or "")
            if out and _has_devanagari(out):
                return out
        except Exception as e:
            sys.stderr.write(f"[translate] attempt {attempt + 1}: {type(e).__name__}: {e}\n")
    return ""


def translate_speech(speech: dict[str, Any], model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Translate every slide's narration, keeping order and numbering."""
    base_url, token = _get_cf_config()
    client = OpenAI(base_url=base_url, api_key=token, timeout=60.0)

    slides = []
    for s in speech["slides"]:
        en = (s.get("speech") or "").strip()
        hi = translate(client, model, en) if en else ""
        if en and not hi:
            sys.stderr.write(f"[slide {s['slide_number']}] translation failed, skipping audio\n")
        slides.append({
            "slide_number": s["slide_number"],
            "heading": s.get("heading", ""),
            "speech_en": en,
            "speech": hi,  # Hindi, same key as speech.json so other tools keep working
        })
    return {"deck_title": speech.get("deck_title", ""), "language": "hi", "slides": slides}


# ----------------------------------------------------------------------
# TTS
# ----------------------------------------------------------------------

def audio_name(n: int) -> str:
    return f"slide_{n:02d}.mp3"


def _one(text: str, path: Path, slow: bool) -> Path:
    gTTS(text=text, lang="hi", slow=slow).save(str(path))
    return path


def synthesize_speech(
    speech: dict[str, Any],
    out_dir: str = "audio_hi",
    workers: int = 1,
    merge: bool = False,
    slow: bool = False,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be at least 1.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items = [
        (slide["slide_number"], (slide.get("speech") or "").strip())
        for slide in speech["slides"]
        if (slide.get("speech") or "").strip()
    ]
    done: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {
            executor.submit(_one, text, out / audio_name(number), slow): number
            for number, text in items
        }
        for future in as_completed(jobs):
            number = jobs[future]
            try:
                done[number] = future.result()
            except (gTTSError, RequestException, OSError) as error:
                sys.stderr.write(f"[{audio_name(number)}] {type(error).__name__}: {error}\n")

    merged = None
    if merge and done:
        merged = out / "full.mp3"
        with open(merged, "wb") as f:
            for n in sorted(done):
                f.write(done[n].read_bytes())
    return {"files": {n: str(p) for n, p in sorted(done.items())}, "merged": str(merged) if merged else None}


def hindi_tts(
    speech_en: dict[str, Any],
    out_dir: str = "audio_hi",
    model: str = DEFAULT_MODEL,
    merge: bool = False,
    workers: int = 1,
    slow: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Importable: English speech dict -> (hindi speech dict, audio result)."""
    hi = translate_speech(speech_en, model)
    return hi, synthesize_speech(hi, out_dir, workers=workers, merge=merge, slow=slow)


def main() -> None:
    ap = argparse.ArgumentParser(description="speech.json -> Hindi translation -> Hindi MP3 per slide using gTTS")
    ap.add_argument("json_file", nargs="?", help="speech.json from speech.py")
    ap.add_argument("--out", default="audio_hi", help="Audio output folder")
    ap.add_argument("--text-out", default="speech_hi.json", help="Where to save the Hindi text")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--slow", action="store_true", help="Generate slower speech")
    ap.add_argument("--merge", action="store_true", help="Also write full.mp3")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--skip-translate", action="store_true", help="Input is already Hindi")
    args = ap.parse_args()

    if not args.json_file:
        ap.print_help()
        sys.exit(1)

    speech = load_speech(args.json_file)
    hi = speech if args.skip_translate else translate_speech(speech, args.model)

    Path(args.text_out).write_text(json.dumps(hi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {args.text_out}")

    res = synthesize_speech(
        hi,
        out_dir=args.out,
        workers=args.workers,
        merge=args.merge,
        slow=args.slow,
    )
    total = len([s for s in hi["slides"] if (s.get("speech") or "").strip()])
    for p in res["files"].values():
        print(p)
    if res["merged"]:
        print(res["merged"])
    print(f"Done: {len(res['files'])}/{len(speech['slides'])} slides")
    if len(res["files"]) < len(speech["slides"]):
        sys.exit(1)


if __name__ == "__main__":
    main()