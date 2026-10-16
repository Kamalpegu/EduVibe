"""
download.py - list / download generated PPTX files, and (optionally) serve them over the backend.

CLI:
  python download.py --list
  python download.py                          # copy newest .pptx to your Downloads folder
  python download.py --name SQL_Overview_hi.pptx
  python download.py --dest D:\\slides
  python download.py --from-url http://127.0.0.1:8000/api/ppt/download/SQL_Overview_hi.pptx

Backend: in backend/main.py add
  sys.path.insert(0, str(SRC / "ppt_maker"))
  import download
  app.include_router(download.router)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from concanate import DEFAULT_SVG_DIR, LANGS, OUT_DIR, build_ppt


def build_presentation(
    lang: str = "en",
    svg_dir: Optional[Path] = None,
    audio_dir: Optional[Path] = None,
    speech_json: Optional[Path] = None,
    out_path: Optional[Path] = None,
    autoplay: bool = True,
    with_audio: bool = True,
    renderer: str = "auto",
) -> Path:
    """Build a PPTX using the same slide, narration, and audio path as downloads."""
    return build_ppt(
        lang=lang,
        svg_dir=svg_dir or DEFAULT_SVG_DIR,
        audio_dir=audio_dir,
        speech_json=speech_json,
        out_path=out_path,
        autoplay=autoplay,
        with_audio=with_audio,
        renderer=renderer,
    )


def list_ppts() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(OUT_DIR.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    i = 1
    while True:
        c = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not c.exists():
            return c
        i += 1


def download_local(name: Optional[str] = None, dest_dir: Optional[Path] = None) -> Path:
    files = list_ppts()
    if not files:
        raise FileNotFoundError(f"No .pptx in {OUT_DIR}. Run concanate.py first.")
    src = OUT_DIR / Path(name).name if name else files[0]
    if not src.exists():
        raise FileNotFoundError(f"{src.name} not found. Available: {[f.name for f in files]}")
    dest_dir = Path(dest_dir or Path.home() / "Downloads")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest_dir / src.name)
    shutil.copy2(src, dest)
    return dest


def download_url(url: str, dest_dir: Optional[Path] = None) -> Path:
    dest_dir = Path(dest_dir or Path.home() / "Downloads")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest_dir / (Path(url.split("?")[0]).name or "presentation.pptx"))
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


# ----------------------------------------------------------------------
# FastAPI router
# ----------------------------------------------------------------------

try:
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import FileResponse
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/ppt", tags=["ppt"])

    class PptReq(BaseModel):
        lang: str = "en"
        autoplay: bool = True
        with_audio: bool = True

    @router.post("/generate")
    def generate(req: PptReq):
        """Build the PPTX from the existing SVG/audio/speech files for the chosen language."""
        if req.lang not in LANGS:
            raise HTTPException(400, f"lang must be one of {list(LANGS)}")
        try:
            p = build_presentation(req.lang, autoplay=req.autoplay, with_audio=req.with_audio)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except SystemExit as e:
            raise HTTPException(500, str(e))
        return {"file": p.name, "download_url": f"/api/ppt/download/{p.name}"}

    @router.get("/files")
    def files():
        return [{"file": p.name, "download_url": f"/api/ppt/download/{p.name}"} for p in list_ppts()]

    @router.get("/download/{name}")
    def download(name: str):
        path = OUT_DIR / Path(name).name
        if path.suffix != ".pptx" or not path.exists():
            raise HTTPException(404, "File not found")
        return FileResponse(
            path, filename=path.name,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
except ImportError:  # CLI works without fastapi installed
    router = None


def main() -> None:
    ap = argparse.ArgumentParser(description="Download generated PPTX")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--name", help="File in ppt_outputs (default: newest)")
    ap.add_argument("--dest", type=Path, help="Target folder (default: your Downloads)")
    ap.add_argument("--from-url", help="Download from the running backend instead")
    a = ap.parse_args()

    if a.list:
        for p in list_ppts():
            print(p.name)
        return
    try:
        out = download_url(a.from_url, a.dest) if a.from_url else download_local(a.name, a.dest)
    except Exception as e:
        sys.exit(f"[error] {e}")
    print(f"Downloaded to {out}")


if __name__ == "__main__":
    main()