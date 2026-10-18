"""FastAPI backend for EduVibe Slide Search and PowerPoint generation.

Run from the project root:
    python -m pip install -r requirements.txt
    python -m playwright install chromium
    python -m uvicorn backend.main:app --app-dir src --reload

POST /api/generate accepts a topic and returns narrated slide data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

SRC = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SRC.parent

load_dotenv(PROJECT_ROOT / ".env", override=False)

for module_path in (
    SRC / "image_create",
    SRC / "start_pro",
    SRC / "voice_over",
):
    module_path_str = str(module_path)
    if module_path_str not in sys.path:
        sys.path.insert(0, module_path_str)

import search_structure
import image_get
from download import build_presentation, router as download_router
from start_query import (
    DEFAULT_MODEL,
    is_comparison_question,
    is_math_question,
    router as query_router,
)
from tts import synthesize_speech as synthesize_slide_audio

logger = logging.getLogger("eduvibe.backend")

app = FastAPI(
    title="EduVibe API",
    description="Generate slide decks, narration, audio, and downloadable PowerPoint files.",
    version="1.0.0",
)
app.include_router(query_router)
app.include_router(download_router)

CACHE_DB = PROJECT_ROOT / ".eduvibe_slide_cache.sqlite3"
AUTH_DB = PROJECT_ROOT / ".eduvibe_accounts.sqlite3"
IS_VERCEL = os.getenv("VERCEL") == "1"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
LOCAL_CACHE_ROOT = Path(tempfile.gettempdir()) / "eduvibe" if IS_VERCEL else PROJECT_ROOT
AUDIO_CACHE_DIR = LOCAL_CACHE_ROOT / ".eduvibe_audio_cache"
SLIDE_SVG_CACHE_DIR = LOCAL_CACHE_ROOT / ".eduvibe_slide_svg_cache"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
AUTH_COOKIE_NAME = "eduvibe_session"
AUTH_SESSION_SECONDS = 30 * 24 * 60 * 60
WEB_DIR = SRC / "frontend"


class GenerateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    lang: Literal["en", "hi"] = Field(
        default="en",
        description="Narration language. Slide titles and bullets are always English.",
    )


class PresentationExportRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    lang: Literal["en", "hi"] = Field(default="en")


class GoogleCredentialRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=10000)


class SavedChat(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=200)
    updatedAt: int
    turns: List[Dict[str, Any]] = Field(max_items=1000)


class SlideResponse(BaseModel):
    title: str
    bullets: List[str]
    say: str
    audioUrl: Optional[str] = None
    svgUrl: Optional[str] = None


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


class _PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        return self._connection.execute(statement.replace("?", "%s"), parameters)


@contextmanager
def _database_connection(local_path: Path) -> Iterator[Any]:
    if IS_VERCEL and not DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail=(
                "Persistent storage is not configured. Add DATABASE_URL with your "
                "Neon Postgres connection string in Vercel Environment Variables, "
                "then redeploy to enable account history."
            ),
        )
    if DATABASE_URL:
        import psycopg

        try:
            with psycopg.connect(
                DATABASE_URL,
                connect_timeout=10,
                prepare_threshold=None,
            ) as connection:
                yield _PostgresConnection(connection)
        except psycopg.Error as exc:
            logger.exception("Could not access the configured Postgres database")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Account history storage is unavailable. Check that DATABASE_URL "
                    "in Vercel points to a reachable Neon Postgres database, then retry."
                ),
            ) from exc
        return

    connection = sqlite3.connect(local_path, timeout=10)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _init_auth_tables(connection: Any) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS google_accounts ("
        "google_sub TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, "
        "picture TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS auth_sessions ("
        "session_hash TEXT PRIMARY KEY, google_sub TEXT NOT NULL, expires_at INTEGER NOT NULL, "
        "FOREIGN KEY (google_sub) REFERENCES google_accounts(google_sub) ON DELETE CASCADE)"
    )
    connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (int(time.time()),))
    connection.execute(
        "CREATE TABLE IF NOT EXISTS user_chats ("
        "google_sub TEXT NOT NULL, chat_id TEXT NOT NULL, chat_json TEXT NOT NULL, "
        "updated_at INTEGER NOT NULL, PRIMARY KEY (google_sub, chat_id), "
        "FOREIGN KEY (google_sub) REFERENCES google_accounts(google_sub) ON DELETE CASCADE)"
    )


def _public_account(row: tuple[str, str, str]) -> dict[str, str]:
    return {"email": row[0], "name": row[1], "picture": row[2]}


def _account_from_session(session_token: Optional[str]) -> Optional[dict[str, str]]:
    if not session_token:
        return None
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        row = connection.execute(
            "SELECT a.email, a.name, a.picture "
            "FROM auth_sessions s JOIN google_accounts a ON a.google_sub = s.google_sub "
            "WHERE s.session_hash = ? AND s.expires_at > ?",
            (token_hash, int(time.time())),
        ).fetchone()
    return _public_account(row) if row else None


def _google_sub_from_session(session_token: Optional[str]) -> Optional[str]:
    if not session_token:
        return None
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        row = connection.execute(
            "SELECT google_sub FROM auth_sessions WHERE session_hash = ? AND expires_at > ?",
            (token_hash, int(time.time())),
        ).fetchone()
    return str(row[0]) if row else None


def _require_google_sub(request: Request) -> str:
    google_sub = _google_sub_from_session(request.cookies.get(AUTH_COOKIE_NAME))
    if not google_sub:
        raise HTTPException(status_code=401, detail="Sign in to access your saved chat history.")
    return google_sub


@app.get("/api/auth/config", tags=["authentication"])
def google_auth_config() -> dict[str, Optional[str]]:
    return {"clientId": GOOGLE_CLIENT_ID or None}


@app.post("/api/auth/google", tags=["authentication"])
def google_sign_in(
    payload: GoogleCredentialRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured. Set GOOGLE_CLIENT_ID in the project .env file and restart EduVibe.",
        )
    try:
        identity = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified. Please try again.") from exc
    except GoogleAuthError as exc:
        logger.exception("Google identity verification service failed")
        raise HTTPException(status_code=503, detail="Google sign-in is temporarily unavailable. Please try again.") from exc

    google_sub = identity.get("sub")
    email = identity.get("email")
    if not google_sub or not email or identity.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="Use a Google account with a verified email address.")

    account = {
        "email": str(email),
        "name": str(identity.get("name") or email),
        "picture": str(identity.get("picture") or ""),
    }
    now = int(time.time())
    session_token = secrets.token_urlsafe(32)
    session_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        existing = connection.execute(
            "SELECT 1 FROM google_accounts WHERE google_sub = ?",
            (str(google_sub),),
        ).fetchone()
        connection.execute(
            "INSERT INTO google_accounts (google_sub, email, name, picture, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(google_sub) DO UPDATE SET "
            "email = excluded.email, name = excluded.name, picture = excluded.picture, updated_at = excluded.updated_at",
            (str(google_sub), account["email"], account["name"], account["picture"], now),
        )
        connection.execute(
            "INSERT INTO auth_sessions (session_hash, google_sub, expires_at) VALUES (?, ?, ?)",
            (session_hash, str(google_sub), now + AUTH_SESSION_SECONDS),
        )
    response.set_cookie(
        AUTH_COOKIE_NAME,
        session_token,
        max_age=AUTH_SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {"user": account, "isNewAccount": existing is None}


@app.get("/api/auth/me", tags=["authentication"])
def current_google_account(request: Request, response: Response) -> Any:
    account = _account_from_session(request.cookies.get(AUTH_COOKIE_NAME))
    if account is None:
        response.status_code = 204
        response.delete_cookie(
            AUTH_COOKIE_NAME,
            path="/",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
        return None
    return account


@app.post("/api/auth/logout", status_code=204, tags=["authentication"])
def google_sign_out(request: Request, response: Response) -> None:
    session_token = request.cookies.get(AUTH_COOKIE_NAME)
    if session_token:
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        with _database_connection(AUTH_DB) as connection:
            _init_auth_tables(connection)
            connection.execute("DELETE FROM auth_sessions WHERE session_hash = ?", (token_hash,))
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )


@app.get("/api/history", tags=["history"])
def get_chat_history(request: Request) -> List[dict[str, Any]]:
    google_sub = _require_google_sub(request)
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        rows = connection.execute(
            "SELECT chat_json FROM user_chats WHERE google_sub = ? ORDER BY updated_at DESC",
            (google_sub,),
        ).fetchall()
    try:
        return [json.loads(row[0]) for row in rows]
    except json.JSONDecodeError as exc:
        logger.exception("A saved chat could not be decoded")
        raise HTTPException(status_code=500, detail="A saved chat could not be loaded.") from exc


@app.put("/api/history/{chat_id}", status_code=204, tags=["history"])
def save_chat_history(chat_id: str, chat: SavedChat, request: Request) -> None:
    if chat.id != chat_id:
        raise HTTPException(status_code=400, detail="The chat ID does not match the saved chat.")
    google_sub = _require_google_sub(request)
    chat_json = json.dumps(chat.dict(), ensure_ascii=False, separators=(",", ":"))
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        connection.execute(
            "INSERT INTO user_chats (google_sub, chat_id, chat_json, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(google_sub, chat_id) DO UPDATE SET "
            "chat_json = excluded.chat_json, updated_at = excluded.updated_at",
            (google_sub, chat.id, chat_json, chat.updatedAt),
        )


@app.delete("/api/history/{chat_id}", status_code=204, tags=["history"])
def delete_chat_history(chat_id: str, request: Request) -> None:
    google_sub = _require_google_sub(request)
    with _database_connection(AUTH_DB) as connection:
        _init_auth_tables(connection)
        connection.execute(
            "DELETE FROM user_chats WHERE google_sub = ? AND chat_id = ?",
            (google_sub, chat_id),
        )


def _cache_key(query: str, lang: str) -> str:
    normalized = re.sub(r"\s+", " ", query).strip().casefold()
    return f"adaptive-slides-v6:{lang}:{normalized}"


def _audio_cache_id(query: str, lang: str) -> str:
    return hashlib.sha256(_cache_key(query, lang).encode("utf-8")).hexdigest()


def _audio_directory(query: str, lang: str) -> Path:
    return AUDIO_CACHE_DIR / lang / _audio_cache_id(query, lang)


def _slide_svg_directory(query: str, lang: str) -> Path:
    return SLIDE_SVG_CACHE_DIR / lang / _audio_cache_id(query, lang)


def _svg_has_current_logo(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8") as svg_file:
        return 'id="eduvibe-logo-bottom-right"' in svg_file.read(2048)


def _blob_path(lang: str, cache_id: str, slide_number: int) -> str:
    return f"slides/{lang}/{cache_id}/slide_{slide_number:02d}.svg"


def _blob_client() -> Any:
    if not os.getenv("BLOB_READ_WRITE_TOKEN") and not os.getenv("BLOB_STORE_ID"):
        raise RuntimeError(
            "Connect a Vercel Blob store or configure BLOB_READ_WRITE_TOKEN."
        )
    try:
        from vercel.blob import sync as blob
    except ImportError as exc:
        raise RuntimeError("Install the vercel-blob package to use persistent slide storage.") from exc
    return blob


def _upload_svg_to_blob(blob: Any, path: Path, pathname: str) -> None:
    try:
        blob.put_blob(
            pathname,
            path.read_bytes(),
            access="private",
            content_type="image/svg+xml",
            allow_overwrite=True,
        )
    except blob.BlobError as exc:
        logger.exception("Could not upload a generated slide to Vercel Blob")
        raise RuntimeError("Could not store generated slides in Vercel Blob.") from exc


def _store_slides_in_blob(
    query: str,
    lang: str,
    slides: List[dict[str, Any]],
    deck: dict[str, Any],
) -> None:
    blob = _blob_client()
    cache_id = _audio_cache_id(query, lang)
    with tempfile.TemporaryDirectory(prefix="eduvibe-svg-") as folder:
        paths = image_get.generate(deck, folder)
        slide_paths = paths[1:]
        if len(slide_paths) != len(slides):
            raise RuntimeError("The SVG renderer returned an unexpected number of slides.")
        with ThreadPoolExecutor(max_workers=min(8, len(slide_paths))) as executor:
            futures = [
                executor.submit(
                    _upload_svg_to_blob,
                    blob,
                    path,
                    _blob_path(lang, cache_id, number),
                )
                for number, path in enumerate(slide_paths, 1)
            ]
            for future in futures:
                future.result()


def _read_slide_svg(lang: str, cache_id: str, slide_number: int) -> bytes:
    if DATABASE_URL:
        blob = _blob_client()
        try:
            return blob.get_blob(
                _blob_path(lang, cache_id, slide_number),
                access="private",
            ).body
        except blob.BlobNotFoundError as exc:
            raise FileNotFoundError("Slide image not found in persistent storage.") from exc
        except blob.BlobError as exc:
            logger.exception("Could not read a slide from Vercel Blob")
            raise RuntimeError("Could not read the slide image from persistent storage.") from exc

    svg_path = SLIDE_SVG_CACHE_DIR / lang / cache_id / f"slide_{slide_number:02d}.svg"
    if not svg_path.is_file():
        raise FileNotFoundError("Slide image not found.")
    return svg_path.read_bytes()


def _materialize_slide_svgs(lang: str, cache_id: str, slide_count: int, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for number in range(1, slide_count + 1):
        path = target_dir / f"slide_{number:02d}.svg"
        path.write_bytes(_read_slide_svg(lang, cache_id, number))


def _slides_with_svg_urls(
    query: str,
    lang: str,
    slides: List[dict[str, Any]],
    deck: Optional[dict[str, Any]] = None,
) -> List[dict[str, Any]]:
    directory = _slide_svg_directory(query, lang)
    if DATABASE_URL:
        if deck is not None:
            _store_slides_in_blob(query, lang, slides, deck)
    else:
        expected_paths = [directory / f"slide_{number:02d}.svg" for number in range(1, len(slides) + 1)]
        has_current_logo = all(_svg_has_current_logo(path) for path in expected_paths)
        if not has_current_logo:
            svg_deck = deck or {
                "deck_title": slides[0]["title"] if slides else "",
                "slides": [
                    {
                        "slide_number": number,
                        "layout": "bullets",
                        "heading": slide["title"],
                        "text": "",
                        "points": slide.get("bullets", []),
                        "numbered": False,
                        "table": None,
                        "formula": None,
                        "source_text": "",
                    }
                    for number, slide in enumerate(slides, 1)
                ],
            }
            image_get.generate(svg_deck, str(directory))

    cache_id = _audio_cache_id(query, lang)
    return [
        {
            **slide,
            "svgUrl": f"/api/slides/{lang}/{cache_id}/{number}.svg",
        }
        for number, slide in enumerate(slides, 1)
    ]


def _cached_slides(query: str, lang: str) -> Optional[List[dict[str, Any]]]:
    with _database_connection(CACHE_DB) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS slide_search_cache "
            "(query_key TEXT PRIMARY KEY, slides_json TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT slides_json FROM slide_search_cache WHERE query_key = ?",
            (_cache_key(query, lang),),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def _cache_slides(query: str, lang: str, slides: List[dict[str, Any]]) -> None:
    with _database_connection(CACHE_DB) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS slide_search_cache "
            "(query_key TEXT PRIMARY KEY, slides_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO slide_search_cache (query_key, slides_json) VALUES (?, ?) "
            "ON CONFLICT(query_key) DO UPDATE SET slides_json = excluded.slides_json",
            (_cache_key(query, lang), json.dumps(slides, ensure_ascii=False)),
        )


def _slide_bullets(slide: dict[str, Any]) -> List[str]:
    bullets = list(slide.get("points") or [])
    table = slide.get("table")
    if table:
        for row in table.get("rows", []):
            bullets.append(" · ".join(str(value) for value in row if value))
    formula = slide.get("formula")
    if formula:
        bullets.append(str(formula.get("equation") or ""))
        bullets.extend(f"{key}: {value}" for key, value in (formula.get("variables") or {}).items())
    text = (slide.get("text") or "").strip()
    if text and not bullets:
        bullets.append(text)
    return [str(item) for item in bullets if str(item).strip()][:6]


def _slide_narration(slide: dict[str, Any]) -> str:
    narration = str(slide.get("say") or "").strip()
    if narration:
        return narration

    content = [str(slide.get("heading") or ""), str(slide.get("text") or "")]
    content.extend(str(point) for point in slide.get("points") or [])
    table = slide.get("table")
    if table:
        content.extend(
            ", ".join(str(cell) for cell in row if cell)
            for row in table.get("rows", [])
        )
    formula = slide.get("formula")
    if formula:
        content.append(str(formula.get("equation") or ""))
    return ". ".join(part.rstrip(". ") for part in content if part.strip())


@app.post(
    "/api/generate",
    response_model=List[SlideResponse],
    response_model_exclude_none=True,
    tags=["presentation"],
)
def generate(req: GenerateRequest) -> List[dict[str, Any]]:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Please enter a topic to search.")
    cached = _cached_slides(query, req.lang)
    if cached is not None:
        try:
            return _slides_with_svg_urls(query, req.lang, cached)
        except OSError as exc:
            logger.exception("Could not render cached slides to SVG")
            raise HTTPException(status_code=502, detail="Could not render cached slides. Please try again.") from exc
        except RuntimeError as exc:
            logger.exception("Could not read cached slide assets")
            raise HTTPException(status_code=502, detail="Could not load cached slides. Please try again.") from exc

    try:
        raw_structure = search_structure.structure_paragraph_sync(
            query,
            model=DEFAULT_MODEL,
            query=query,
            math_question=is_math_question(query),
            comparison_question=is_comparison_question(query),
            direct_query=True,
            narration_lang=req.lang,
        )
        deck = search_structure.structure_to_slides(raw_structure)
        if not deck["slides"]:
            raise HTTPException(status_code=502, detail="The AI service returned no slides.")

        deck["slides"] = deck["slides"][:8]
        slides = [
            {
                "title": item.get("heading") or deck.get("deck_title") or f"Slide {item['slide_number']}",
                "bullets": _slide_bullets(item),
                "say": _slide_narration(item),
            }
            for item in deck["slides"][:8]
        ]
        if not slides:
            raise HTTPException(status_code=502, detail="The AI service returned no slides.")
        if req.lang == "hi":
            missing_narration = [
                number
                for number, slide in enumerate(slides, 1)
                if not re.search(r"[\u0900-\u097F]", slide["say"])
            ]
            if missing_narration:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not generate Hindi narration for slide(s): {', '.join(map(str, missing_narration))}. Please try again.",
                )
        slides = _slides_with_svg_urls(query, req.lang, slides, deck)
        _cache_slides(query, req.lang, slides)
        return slides
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("Could not render or cache generated slides")
        raise HTTPException(status_code=502, detail="Could not render or cache generated slides. Please try again.") from exc
    except RuntimeError as exc:
        logger.exception("Slide search generation failed")
        raise HTTPException(status_code=502, detail="Could not generate slides. Please try again.") from exc
    except SystemExit as exc:
        logger.exception("Slide search generation failed")
        raise HTTPException(
            status_code=502,
            detail="The AI service failed while generating slides. Please try again.",
        ) from exc


@app.get("/api/slides/{lang}/{cache_id}/{slide_number}.svg", tags=["presentation"])
def get_slide_svg(lang: Literal["en", "hi"], cache_id: str, slide_number: int) -> Response:
    if not re.fullmatch(r"[a-f0-9]{64}", cache_id) or not 1 <= slide_number <= 8:
        raise HTTPException(status_code=404, detail="Slide image not found.")
    try:
        svg = _read_slide_svg(lang, cache_id, slide_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Slide image not found.")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=svg, media_type="image/svg+xml")


@app.post("/api/ppt/export", tags=["ppt"])
def export_presentation(req: PresentationExportRequest) -> FileResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="A topic is required to export a presentation.")
    slides = _cached_slides(query, req.lang)
    if not slides:
        raise HTTPException(status_code=404, detail="No generated slides were found for this conversation.")

    output = Path(tempfile.gettempdir()) / f"eduvibe-{secrets.token_hex(16)}.pptx"
    try:
        speech_data = {
            "deck_title": query,
            "slides": [
                {
                    "slide_number": number,
                    "heading": slide["title"],
                    "speech": slide.get("say", "").strip(),
                }
                for number, slide in enumerate(slides, 1)
            ],
        }
        audio_dir = _audio_directory(query, req.lang)
        expected_audio = [
            audio_dir / f"slide_{number:02d}.mp3"
            for number in range(1, len(slides) + 1)
        ]
        if not all(path.is_file() and path.stat().st_size > 0 for path in expected_audio):
            with tempfile.TemporaryDirectory(prefix="eduvibe-export-audio-") as audio_tmp:
                synthesized = synthesize_slide_audio(
                    speech_data,
                    out_dir=audio_tmp,
                    lang="hi" if req.lang == "hi" else "en",
                )
                missing_audio = [
                    number
                    for number in range(1, len(slides) + 1)
                    if number not in synthesized["files"]
                    or not Path(synthesized["files"][number]).is_file()
                    or Path(synthesized["files"][number]).stat().st_size == 0
                ]
                if missing_audio:
                    raise RuntimeError(
                        "Could not generate narration audio for slide(s): "
                        + ", ".join(map(str, missing_audio))
                    )
                audio_dir.mkdir(parents=True, exist_ok=True)
                for number in range(1, len(slides) + 1):
                    shutil.copyfile(
                        synthesized["files"][number],
                        audio_dir / f"slide_{number:02d}.mp3",
                    )

        with tempfile.TemporaryDirectory(prefix="eduvibe-export-") as export_dir:
            export_root = Path(export_dir)
            export_svg_dir = export_root / "svgs"
            export_svg_dir.mkdir()
            _materialize_slide_svgs(
                req.lang,
                _audio_cache_id(query, req.lang),
                len(slides),
                export_svg_dir,
            )
            speech_json = export_root / "speech.json"
            speech_json.write_text(json.dumps(speech_data, ensure_ascii=False), encoding="utf-8")
            build_presentation(
                lang=req.lang,
                svg_dir=export_svg_dir,
                audio_dir=audio_dir,
                speech_json=speech_json,
                out_path=output,
                with_audio=True,
                renderer="auto",
            )
    except (OSError, ImportError, RuntimeError, SystemExit, ValueError) as exc:
        output.unlink(missing_ok=True)
        logger.exception("Could not create PowerPoint from generated slides")
        raise HTTPException(
            status_code=502,
            detail=f"Could not create the PowerPoint file with narration: {exc}",
        ) from exc

    safe_title = re.sub(r"[^\w-]+", "_", query, flags=re.UNICODE).strip("_")[:60] or "EduVibe"
    return FileResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{safe_title}.pptx",
        background=BackgroundTask(output.unlink, missing_ok=True),
    )


@app.get("/api/audio/{lang}/{cache_id}/{slide_number}", tags=["presentation"])
def get_slide_audio(lang: Literal["en", "hi"], cache_id: str, slide_number: int):
    if not re.fullmatch(r"[a-f0-9]{64}", cache_id) or not 1 <= slide_number <= 8:
        raise HTTPException(status_code=404, detail="Audio file not found.")
    audio_path = AUDIO_CACHE_DIR / lang / cache_id / f"slide_{slide_number:02d}.mp3"
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return FileResponse(audio_path, media_type="audio/mpeg")


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
