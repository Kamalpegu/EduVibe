# EduVibe Workflow

This document describes how the current EduVibe application works, from a user's search to generated slides, narration, account history, and optional PowerPoint export.

## Project workflow tree

```text
EduVibe
|
+-- Browser application (src/frontend)
|   +-- TopBar
|   |   +-- EduVibe logo and theme
|   |   +-- Narration language (English or Hindi)
|   |   +-- Top-bar Download: all slides from the last-used turn as PPTX
|   |   +-- Google account menu
|   +-- Sidebar
|   |   +-- New chat
|   |   +-- Per-chat history list
|   +-- Thread
|   |   +-- User query
|   |   +-- Loading, error, or generated slide deck
|   |   +-- Slide navigation and audio controls
|   +-- Composer
|       +-- Topic/question -> POST /api/generate
|
+-- FastAPI application (src/backend/main.py)
|   +-- Presentation API
|   |   +-- Validate query and narration language
|   |   +-- Check SQLite slide cache
|   |   +-- One Cloudflare call -> generate slides and narration together
|   |   +-- image_create/image_get.py -> render each slide as SVG
|   |   +-- Return slide data and same-origin SVG URLs to browser
|   +-- Authentication API
|   |   +-- Google Identity Services config
|   |   +-- Verify Google ID token
|   |   +-- Create/update account and issue HttpOnly session cookie
|   +-- Account history API
|   |   +-- Load, save, and delete chats scoped to Google account
|   +-- Audio and PowerPoint APIs
|
+-- AI and processing modules (src)
|   +-- image_create/search_structure.py Topic/question -> slides and narration (one Cloudflare Workers AI call)
|   +-- start_pro/start_query.py       Optional topic -> factual paragraph endpoint
|   +-- voice_over/speech.py          CLI slide narration (Cloudflare Workers AI)
|   +-- voice_over/htts.py            CLI English-to-Hindi narration translation
|   +-- frontend/services/tts.js      Browser narration with Puter.js
|   +-- voice_over/tts.py             CLI MP3 generation with gTTS
|   +-- start_pro/concanate.py        Saved SVG/audio/narration -> PowerPoint
|
+-- Local configuration and persistence
  +-- .env                         Shared local Cloudflare and Google credentials (never commit)
  +-- .eduvibe_slide_cache.sqlite3 Generated slides cached by normalized query and language
    +-- .eduvibe_slide_svg_cache/    SVGs rendered by image_get.py for web slides
    +-- .eduvibe_accounts.sqlite3     Google accounts, hashed sessions, and signed-in chats
    +-- Browser localStorage           Guest chat history and display preferences
```

## Web search-to-slides flow

```text
User enters a topic
  -> Composer submits POST /api/generate
  -> FastAPI validates query (1-4000 characters) and narration language (en or hi)
  -> Look up normalized query + language in .eduvibe_slide_cache.sqlite3
       |
       +-- Cache hit
       |    -> Load cached slide data
       |    -> Ensure matching SVG files exist (render from cached data if missing)
       |
       +-- Cache miss
            -> search_structure.structure_paragraph_sync (direct-query mode)
               One Cloudflare Workers AI call -> answer, 1-8 slides, and spoken narration
               Math questions request equations, ordered steps, and a final answer
               Comparison/difference questions require a labeled table of relevant criteria
               Hindi narration is generated in the same call when Hindi is selected
            -> image_get.generate(deck) -> render and cache slide SVG files
            -> Save slide data and SVG URLs in SQLite cache
       |
       v
  Return [{ title, bullets, say, svgUrl }, ...] to browser
  -> Browser loads SVG from GET /api/slides/{lang}/{cache_id}/{slide_number}.svg
  -> Display that SVG as the slide image in the chat thread
       |
       +-- User selects slide -> update current slide
       +-- User plays audio -> Puter.js browser TTS speaks `say`
       +-- Audio ends -> automatically play next slide
       +-- Slide download -> save the current rendered SVG
       +-- Top-bar Download -> export all slides in the last-used turn as PPTX
```

`image_get.py` is used by the web backend as well as the CLI: it renders the structured slide deck into SVG files stored in `.eduvibe_slide_svg_cache/`, with the white EduVibe logo in the bottom-right corner of every slide. Slide headings, layouts, and count (1-8) are selected from each query's actual explanation; no generic section sequence is imposed. Math questions request equations, ordered working, and final answers, which are rendered on the slides. Comparison and difference questions include a labeled comparison table rendered directly on the slide. For cached slide data without SVGs or with an older-positioned logo, the backend renders them again from the cached titles and bullets. The API returns an SVG URL per slide; the browser displays that file and downloads the same rendered SVG. The generated slide text remains English. The language selector affects narration only. Web playback uses Puter.js (AWS Polly voices); it does not call the Python gTTS scripts.

## Chat history and account workflow

### Guest

1. On startup, the browser loads guest chats from `localStorage`.
2. New searches, turn status, slides, and selected-slide changes update that guest history.
3. Guest chats remain on that browser and are not automatically moved into an account.

### Signed in with Google

1. The browser requests `GET /api/auth/config` and renders the Google Identity Services button when a client ID is configured.
2. Google returns an ID token to the browser. The browser posts it to `POST /api/auth/google`.
3. The backend verifies the token and verified email against the configured Google client ID.
4. The backend upserts the account by Google's stable `sub` identifier and creates a random session token. Only a hash of the token is stored; the raw token is set in an HttpOnly, SameSite cookie.
5. The browser calls `GET /api/history`. The backend derives the account from the session cookie and returns only that account's chats.
6. Chat saves and deletes use `PUT /api/history/{chat_id}` and `DELETE /api/history/{chat_id}`. Every operation is scoped to the authenticated Google account on the server.
7. On sign-out, pending history saves are flushed, `POST /api/auth/logout` invalidates the session, and the browser returns to guest history.

Each Google account has its own chat list. Google Cloud OAuth audience, test-user status, Workspace policy, and the exact authorized JavaScript origin determine whether Google permits sign-in; EduVibe itself does not maintain an email allowlist.

## Command-line presentation workflow

The optional CLI file workflow uses Cloudflare and Google TTS services, so it requires network access. It is separate from the browser's Puter narration:

```text
Topic
  -> start_pro/start_query.py       writes a factual paragraph
  -> image_create/search_structure.py --format slides-json
  -> image_create/image_get.py      renders slide SVGs (also used by the web backend)
  -> voice_over/speech.py           writes English narration JSON
  -> voice_over/tts.py              creates English MP3s with gTTS
  -> voice_over/htts.py             translates narration and creates Hindi MP3s
  -> start_pro/concanate.py         assembles the chosen language into a PPTX
```

The detailed commands and dependencies are in [README.md](./README.md). Chromium is required for PowerPoint rendering, not for running the web app.

## Main routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Confirm the backend is responding |
| `POST` | `/api/generate` | Generate or retrieve cached slide and narration data |
| `GET` | `/api/slides/{lang}/{cache_id}/{slide_number}.svg` | Serve a rendered SVG created by `image_get.py` |
| `GET` | `/api/auth/config` | Return the public Google OAuth client ID, if configured |
| `POST` | `/api/auth/google` | Verify Google credential and create a signed-in session |
| `GET` | `/api/auth/me` | Restore the current signed-in account |
| `POST` | `/api/auth/logout` | Invalidate the current session |
| `GET` | `/api/history` | Load the signed-in user's chats |
| `PUT` | `/api/history/{chat_id}` | Save/update one signed-in chat |
| `DELETE` | `/api/history/{chat_id}` | Delete one signed-in chat |
| `GET` | `/api/audio/{lang}/{cache_id}/{slide_number}` | Serve an MP3 from the backend audio-cache directory, when present |
| `POST` | `/api/ppt/export` | Build and download the selected query's slides as a narrated PPTX |
| `POST` | `/api/ppt/generate` | Assemble an existing presentation into PowerPoint using `download.py` |
| `GET` | `/api/ppt/files` | List generated PowerPoint files |
| `GET` | `/api/ppt/download/{name}` | Download a generated PowerPoint |

## Runtime configuration

- Cloudflare Workers AI and Google client credentials are loaded from the project-root `.env`; standalone scripts discover that same shared file.
- Web PPTX exports use `src/start_pro/download.py` and `concanate.py`; per-slide narration MP3s are synthesized with the existing `src/voice_over/tts.py` service, cached by query and language, and embedded in the PowerPoint.
- `GOOGLE_CLIENT_ID` is read from the project-root `.env` when the backend starts.
- Never put API tokens or client secrets in frontend files or commit them.
- Run the backend from the project root as shown in [README.md](./README.md); the frontend is served by FastAPI.
