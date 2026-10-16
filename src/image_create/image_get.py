"""
image_get.py - slides JSON (from search_structure.py) -> one SVG per slide.

python search_structure.py "<paragraph>" --format slides-json --out slides.json
python image_get.py slides.json --out slides_svg
python image_get.py --paragraph "<paragraph>" --out slides_svg
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

W, H = 1280, 720
PAD = 80
CW = W - 2 * PAD
BODY_TOP = 190
BODY_MAX = 690 - 30 - BODY_TOP

BG1, BG2 = "#0f172a", "#1e293b"
ACCENT, ACCENT2 = "#38bdf8", "#818cf8"
TEXT, MUTED, CARD = "#f1f5f9", "#94a3b8", "#1e293b"
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
MONO = "Consolas, 'Courier New', monospace"
LOGO_PATH = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "eduvibe-slide-logo-white.png"


def logo_data_uri() -> str:
    encoded_logo = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_logo}"


def wrap(text: str, fs: float, width: float) -> list[str]:
    cpl = max(8, int(width / (fs * 0.52)))
    return textwrap.wrap(str(text), cpl) or [""]


def txt(x, y, s, fs, fill=TEXT, weight="normal", anchor="start", font=FONT) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}" font-family="{font}">{escape(str(s))}</text>')


def build(s: dict[str, Any], fs: int) -> tuple[list[str], float]:
    """Return svg elements (relative coords) and total height for a given base font size."""
    layout = s["layout"]
    boxed = layout in ("plain_text", "definition", "example")
    ix = 40 if boxed else 0
    iw = CW - (80 if boxed else 0)
    els: list[str] = []
    y = 36.0 if boxed else 0.0

    if s.get("text"):
        lead = bool(s.get("points") or s.get("table"))
        size = fs - 4 if lead else fs
        for i, line in enumerate(wrap(s["text"], size, iw)):
            els.append(txt(ix, y + size + i * size * 1.4, line, size, MUTED if lead else TEXT))
        y += len(wrap(s["text"], size, iw)) * size * 1.4 + 18

    pfs = fs - 2
    for n, p in enumerate(s.get("points") or [], 1):
        lines = wrap(p, pfs, iw - 56)
        cy = y + pfs * 0.75
        if s.get("numbered"):
            els.append(f'<circle cx="{ix + 16}" cy="{cy:.1f}" r="16" fill="{ACCENT}"/>')
            els.append(txt(ix + 16, cy + 6, n, 16, BG1, "bold", "middle"))
        else:
            els.append(f'<circle cx="{ix + 10}" cy="{cy:.1f}" r="7" fill="{ACCENT}"/>')
        for i, line in enumerate(lines):
            els.append(txt(ix + 48, y + pfs + i * pfs * 1.4, line, pfs))
        y += len(lines) * pfs * 1.4 + 14

    tbl = s.get("table")
    if tbl:
        cols, rows = tbl["columns"], tbl["rows"]
        rows = [row if isinstance(row, (list, tuple)) else [row] for row in rows]
        tfs = max(13, fs - 8)
        weights = [max(8, len(str(c)), *(len(str(r[i])) for r in rows if i < len(r))) for i, c in enumerate(cols)]
        widths = [CW * w / sum(weights) for w in weights]
        xs = [sum(widths[:i]) for i in range(len(cols))]
        hh = tfs * 1.4 + 24
        els.append(f'<rect x="0" y="{y:.1f}" width="{CW}" height="{hh:.1f}" rx="8" fill="{ACCENT2}"/>')
        for i, c in enumerate(cols):
            els.append(txt(xs[i] + 14, y + hh / 2 + tfs * 0.35, c, tfs, BG1, "bold"))
        y += hh
        for ri, row in enumerate(rows):
            cells = [wrap(row[i] if i < len(row) else "", tfs, widths[i] - 28) for i in range(len(cols))]
            rh = max(len(c) for c in cells) * tfs * 1.35 + 22
            fill = CARD if ri % 2 == 0 else "#162033"
            els.append(f'<rect x="0" y="{y:.1f}" width="{CW}" height="{rh:.1f}" fill="{fill}"/>')
            for i, lines in enumerate(cells):
                for li, line in enumerate(lines):
                    els.append(txt(xs[i] + 14, y + 11 + tfs + li * tfs * 1.35, line, tfs,
                                   ACCENT if i == 0 else TEXT, "bold" if i == 0 else "normal"))
            y += rh
        y += 14

    f = s.get("formula")
    if f:
        eq = f["equation"]
        bh = fs * 2 + 20
        els.append(f'<rect x="0" y="{y:.1f}" width="{CW}" height="{bh:.1f}" rx="12" fill="{CARD}" '
                   f'stroke="{ACCENT}" stroke-width="2"/>')
        els.append(txt(CW / 2, y + bh / 2 + fs * 0.35, eq, fs + 2, ACCENT, "bold", "middle", MONO))
        y += bh + 18
        for k, v in (f.get("variables") or {}).items():
            line = f"{k}: {v}"
            els.append(txt(ix, y + pfs, line, pfs, MUTED))
            y += pfs * 1.5

    if boxed:
        h = y + 24
        els.insert(0, f'<rect x="0" y="0" width="{CW}" height="{h:.1f}" rx="16" fill="{CARD}"/>')
        els.insert(1, f'<rect x="0" y="0" width="8" height="{h:.1f}" rx="4" fill="{ACCENT}"/>')
        y = h
    return els, y


def frame(inner: str, deck: str, n: int | None, total: int) -> str:
    footer = ""
    if n is not None:
        footer = (txt(PAD, 690, deck, 16, MUTED) + txt(940, 690, f"{n} / {total}", 16, MUTED, anchor="end"))
    logo = (
        f'<image id="eduvibe-logo-bottom-right" href="{logo_data_uri()}" '
        'x="1000" y="625" width="200" height="55" preserveAspectRatio="xMaxYMid meet"/>'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/></linearGradient>
<linearGradient id="ac" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT2}"/></linearGradient>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{logo}
{inner}
{footer}
</svg>'''


def slide_svg(s: dict[str, Any], deck: str, total: int) -> str:
    heading = s.get("heading") or deck
    fs, els, h = 34, [], 0.0
    for fs in range(34, 13, -2):
        els, h = build(s, fs)
        if h <= BODY_MAX:
            break
    hs = 46 if len(heading) < 32 else 38
    inner = (
        f'<rect x="0" y="0" width="{W}" height="10" fill="url(#ac)"/>'
        + txt(PAD, 115, heading, hs, TEXT, "bold")
        + f'<rect x="{PAD}" y="135" width="140" height="5" rx="2.5" fill="url(#ac)"/>'
        + f'<g transform="translate({PAD},{BODY_TOP})">' + "".join(els) + "</g>"
    )
    return frame(inner, deck, s["slide_number"], total)


def cover_svg(deck: str, total: int) -> str:
    lines = wrap(deck or "Presentation", 64, W - 2 * PAD - 40)
    y0 = H / 2 - len(lines) * 40
    t = "".join(txt(W / 2, y0 + i * 80, l, 64, TEXT, "bold", "middle") for i, l in enumerate(lines))
    inner = (
        f'<rect x="0" y="0" width="{W}" height="10" fill="url(#ac)"/>'
        + t
        + f'<rect x="{W / 2 - 80}" y="{y0 + len(lines) * 80 - 20}" width="160" height="6" rx="3" fill="url(#ac)"/>'
        + txt(W / 2, y0 + len(lines) * 80 + 40, f"{total} slides", 22, MUTED, anchor="middle")
    )
    return frame(inner, deck, None, total)


def generate(deck: dict[str, Any], out_dir: str = "slides_svg") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slides = deck.get("slides", [])
    title = deck.get("deck_title", "")
    paths = []

    p = out / "slide_00_cover.svg"
    p.write_text(cover_svg(title, len(slides)), encoding="utf-8")
    paths.append(p)

    for s in slides:
        p = out / f"slide_{s['slide_number']:02d}.svg"
        p.write_text(slide_svg(s, title, len(slides)), encoding="utf-8")
        paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Slides JSON -> SVG slides")
    ap.add_argument("json_file", nargs="?", help="slides-json file (or pipe via stdin)")
    ap.add_argument("--paragraph", help="Run search_structure.py pipeline on this paragraph first")
    ap.add_argument("--out", default="slides_svg", help="Output folder")
    args = ap.parse_args()

    if args.paragraph:
        from search_structure import structure_paragraph_sync, structure_to_slides
        deck = structure_to_slides(structure_paragraph_sync(args.paragraph))
    elif args.json_file:
        deck = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    elif not sys.stdin.isatty():
        deck = json.loads(sys.stdin.read())
    else:
        ap.print_help()
        sys.exit(1)

    for p in generate(deck, args.out):
        print(p)


if __name__ == "__main__":
    main()