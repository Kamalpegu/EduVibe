"""
tts.py - speech.json -> MP3 per slide (+ optional merged file).

python tts.py speech.json --out audio
python tts.py speech.json --out audio --merge
python tts.py speech.json --lang en --slow

pip install gTTS
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import sys
from pathlib import Path
from typing import Any

from gtts import gTTS
from gtts.tts import gTTSError
from requests.exceptions import RequestException


def load_speech(path: str) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    raw = re.sub(r"```(?:json)?", "", raw).strip()  # tolerate pasted code fences
    return json.loads(raw)


def audio_name(n: int) -> str:
    return f"slide_{n:02d}.mp3"


def _one(text: str, path: Path, lang: str, slow: bool) -> Path:
    gTTS(text=text, lang=lang, slow=slow).save(str(path))
    return path


def synthesize_speech(
    speech: dict[str, Any],
    out_dir: str = "audio",
    workers: int = 1,
    merge: bool = False,
    lang: str = "en",
    slow: bool = False,
) -> dict[str, Any]:
    """Importable entry point. Returns {slide_number: file path, 'merged': path|None}."""
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
            executor.submit(_one, text, out / audio_name(number), lang, slow): number
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
        with open(merged, "wb") as f:  # MP3 frames concatenate cleanly
            for n in sorted(done):
                f.write(done[n].read_bytes())
    return {"files": {n: str(p) for n, p in sorted(done.items())}, "merged": str(merged) if merged else None}


def main() -> None:
    ap = argparse.ArgumentParser(description="speech.json -> MP3 per slide using gTTS")
    ap.add_argument("json_file", nargs="?", help="speech.json from speech.py")
    ap.add_argument("--out", default="audio", help="Output folder")
    ap.add_argument("--workers", type=int, default=1, help="Concurrent TTS requests")
    ap.add_argument("--lang", default="en", help="gTTS language code (default: en)")
    ap.add_argument("--slow", action="store_true", help="Generate slower speech")
    ap.add_argument("--merge", action="store_true", help="Also write full.mp3 (all slides in order)")
    args = ap.parse_args()

    if not args.json_file:
        ap.print_help()
        sys.exit(1)

    speech = load_speech(args.json_file)
    res = synthesize_speech(
        speech,
        out_dir=args.out,
        workers=args.workers,
        merge=args.merge,
        lang=args.lang,
        slow=args.slow,
    )

    total = len([s for s in speech["slides"] if (s.get("speech") or "").strip()])
    for n, p in res["files"].items():
        print(p)
    if res["merged"]:
        print(res["merged"])
    print(f"Done: {len(res['files'])}/{total} slides")
    if len(res["files"]) < total:
        sys.exit(1)


if __name__ == "__main__":
    main()