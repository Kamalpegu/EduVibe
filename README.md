# EduVibe

EduVibe is a chat-style learning app that turns a topic into English slides with narrated audio. Choose English or Hindi for the narration; the slide headings and content stay in English. Signed-in users have separate account histories; guest chat history is stored in the browser.

Slide topics and deck length are generated from the specific question and its supporting content (1-8 slides), rather than following a fixed outline. Math questions receive worked steps with equations and a clearly stated final answer. Questions asking for comparisons or differences include a labeled table of the relevant criteria.

The top-bar **Download** button exports every slide in the last-used search turn as a narrated PowerPoint (`.pptx`), with a voice track on each slide. Each slide's own **Download slide** action continues to save only that slide as an SVG.

## Quick start

### Windows (PowerShell)

Open a terminal in the project root (the folder containing this README), then run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If a project virtual environment already exists, activate or use it instead of creating another one. For example, this project may already have `venv`:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy the example environment file and fill in your Cloudflare credentials and Google client ID (see below). You can store these values in the project-root `.env`; the backend loads it automatically. Then launch the web app:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --app-dir src --reload
```

Open <http://127.0.0.1:8000>. Leave the terminal running while you use EduVibe. Press **Ctrl+C** in that terminal to stop the server.

If you used the existing `venv`, replace `.venv` with `venv` in the commands above.

### macOS and Linux

Open a terminal in the project root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.main:app --app-dir src --reload
```

Open <http://127.0.0.1:8000>. Press **Ctrl+C** to stop the server.

## Deploy to PythonAnywhere

EduVibe is a FastAPI/ASGI app. PythonAnywhere's current ASGI hosting is experimental and may need to be enabled for your account; it is separate from the usual WSGI Web tab setup. Review the [PythonAnywhere ASGI guide](https://help.pythonanywhere.com/pages/ASGICommandLine/) and request access through the account feedback link if ASGI hosting is not enabled. PythonAnywhere currently documents deploying ASGI apps with its `pa` command-line tool.

1. Push the project to GitHub, then open a Bash console on PythonAnywhere and clone your repository:

   ```bash
   cd ~
   git clone https://github.com/YOUR_GITHUB_USERNAME/EduVibe.git
   cd ~/EduVibe
   ```

2. Create a PythonAnywhere virtual environment using a Python version available to your account, then install the project requirements:

   ```bash
   mkvirtualenv eduvibe --python=python3.13
   pip install -r requirements.txt
   ```

   If `python3.13` is not available to your account, choose an available Python version and use that same version for the virtual environment.

3. Create the deployment's private root `.env` from the example and enter the existing credentials using the PythonAnywhere file editor:

   ```bash
   cp .env.example .env
   chmod 600 .env
   nano .env
   ```

   Keep the populated `.env` on the server only; do not upload it to GitHub. The backend and standalone processing scripts load this shared file.

4. Add `https://YOURUSERNAME.pythonanywhere.com` as an **Authorized JavaScript origin** for your Google OAuth web client, and set `GOOGLE_CLIENT_ID` in the server `.env` to that client ID. Use your actual PythonAnywhere domain (including the regional suffix if your account uses one).

5. Install the PythonAnywhere deployment CLI and create the ASGI website. Replace `YOURUSERNAME` and the domain with your account details:

   ```bash
   pip install --upgrade pythonanywhere
   pa website create \
     --domain YOURUSERNAME.pythonanywhere.com \
     --command '/home/YOURUSERNAME/.virtualenvs/eduvibe/bin/uvicorn --app-dir /home/YOURUSERNAME/EduVibe/src --uds ${DOMAIN_SOCKET} backend.main:app'
   ```

   The command is intentionally quoted so PythonAnywhere can substitute `${DOMAIN_SOCKET}`. The app serves its frontend through FastAPI, so it does not require separate static-file mappings.

6. Visit `https://YOURUSERNAME.pythonanywhere.com/api/health`; expect `{"status":"ok"}`. After deploying code updates, run `pa website reload --domain YOURUSERNAME.pythonanywhere.com`.

PythonAnywhere's ASGI hosting is experimental; check its current account, pricing, and external-network-access requirements before relying on it in production. EduVibe needs outbound HTTPS access to Google token verification, Cloudflare Workers AI, and Puter.js in the browser. SQLite account/history data and generated caches are stored under the project directory, so keep that directory persistent and back up `.eduvibe_accounts.sqlite3` if you need to preserve signed-in users' chat history. PowerPoint export should be tested on the hosted environment because SVG-to-image rendering depends on the server's installed libraries.

## Deploy to Vercel

Vercel functions do not provide persistent local files. EduVibe uses Neon Postgres for account, chat, and slide-response data, and a private Vercel Blob store for rendered slide SVGs. The backend creates its tables automatically the first time it accesses Neon. Local development continues to use SQLite and local SVG files unless `DATABASE_URL` is set.

1. Create a Neon Postgres database and copy its pooled connection string. Require TLS (`sslmode=require`). Vercel's Python runtime must be Python 3.10 or later for the Blob SDK.
2. In Vercel, create a private Blob store for the project and copy its read-write token.
3. Import the project’s GitHub repository into Vercel with the project root as the **Root Directory**. Vercel detects the root [`index.py`](./index.py) FastAPI entrypoint and uses [`requirements.txt`](./requirements.txt) to install dependencies.
4. In **Project Settings → Environment Variables**, configure:

   - `DATABASE_URL` — Neon connection string
   - `BLOB_READ_WRITE_TOKEN` — token for the Vercel Blob store
   - `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` — Workers AI
   - `GOOGLE_CLIENT_ID` — Google sign-in web client ID
   - `OPENAI_API_KEY` — only if required by the selected query/AI integration

   Set variables for the environments where you will deploy (Production, and Preview if needed), then redeploy after changing them. Do not upload or commit the populated local `.env`.

5. Add the deployed Vercel domain (for example, `https://your-project.vercel.app`) to the Google OAuth client’s **Authorized JavaScript origins**.
6. Deploy and check `https://your-project.vercel.app/api/health`; expect `{"status":"ok"}`. Test sign-in, a slide search, reopening the generated SVG, and PowerPoint export.

New sign-ins and generated slide caches are stored in Neon; slide SVGs are kept in the private Blob store and served through EduVibe’s API. Existing local SQLite accounts and history are not copied automatically and will not appear in the deployed database. Web narration continues to use browser-based Puter.js. Export uses temporary function storage and depends on the runtime’s ability to render the SVG slides; verify this feature on the deployed project.

## Cloudflare credentials

Slide and narration generation use Cloudflare Workers AI. Create an API token with permission to run Workers AI models and obtain your Cloudflare account ID. Copy `.env.example` to `.env` in the project root and fill in:

```dotenv
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token
```

Keep real credentials only in the project-root `.env`, which is excluded from Git. Never paste secrets into source files or commit them. The backend and standalone processing scripts load this shared root `.env`; you do not need a separate `.env` in each source folder. Existing process environment variables take precedence.

## Google sign-in and account creation

The first successful Google sign-in creates an EduVibe account; later sign-ins return to that account. To enable it:

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project and configure the OAuth consent screen. Set the audience to **External**. While the app's publishing status is **Testing**, only accounts listed under **Test users** can sign in; to let any Google account sign in, publish the app from the OAuth audience settings.
2. Create an OAuth client ID with application type **Web application**.
3. Add the exact app origin to **Authorized JavaScript origins** (for local development, add `http://127.0.0.1:8000` or `http://127.0.0.1:8001`, matching the port you open; add `localhost` separately if you use it). This is distinct from **Authorized redirect URIs**.
4. Copy `.env.example` to `.env` in the project root and set `GOOGLE_CLIENT_ID` to that web client ID. The client ID is public configuration; never put a client secret in browser code.
5. Install the updated Python dependencies and restart the backend:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --app-dir src --reload
   ```

   Use `.venv/bin/python` on macOS/Linux.

Google Identity Services signs in from the browser; the backend accepts any Google account that returns a valid ID token with a verified email, records the account by Google's stable account ID, and issues a random, HttpOnly, SameSite session cookie. EduVibe does not maintain an email allowlist. Google Cloud's consent-screen audience, publishing status, and authorized JavaScript origins still control who Google permits to reach the app. Session tokens are stored hashed in `.eduvibe_accounts.sqlite3`; the database is local and ignored by Git. Signed-in chats are stored in that database under the verified Google account, so each account has a separate history that is restored after sign-in. Guest chats remain in the browser's local storage and are not merged into an account. The account database is local to this server, so accounts on different devices or server instances share history only when they connect to the same deployed backend and database. Use HTTPS in production so the cookie is Secure.

The web app uses Puter.js TTS in the browser for English and Hindi narration (AWS Polly Joanna for English and Aditi for Hindi). It loads the Puter.js SDK from `https://js.puter.com/v2/`; playback therefore requires internet access. Puter may request its own authorization for TTS; this is separate from EduVibe's Google account. TTS usage follows Puter's user-pays model. Slide content and narration are generated together in one Cloudflare Workers AI request; Hindi narration is generated in Hindi while slide content remains English. The language selector changes narration only, not the generated English slide content.

The command-line tools `src/voice_over/tts.py` and `src/voice_over/htts.py` continue to generate MP3 files with gTTS. They require internet access to Google's text-to-speech service, which may rate-limit or block requests. The Hindi CLI also uses the Cloudflare credentials above for translation.

## Verify the app is running

With Uvicorn running, open these addresses in your browser:

- App: <http://127.0.0.1:8000>
- Health check: <http://127.0.0.1:8000/api/health> (expected response: `{"status":"ok"}`)
- Interactive API docs: <http://127.0.0.1:8000/docs>

You can check the health endpoint from PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Or from macOS/Linux:

```bash
curl http://127.0.0.1:8000/api/health
```

To try slide generation directly, send a request from PowerShell:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/generate `
  -ContentType 'application/json' `
  -Body '{"query":"How do solar panels work?","lang":"en"}'
```

Set `lang` to `hi` to generate the same English slide content with Hindi narration. Slide generation makes Cloudflare requests; playing narration invokes Puter.js in the browser.

## Generate a presentation from the command line

The scripts under `src` can also be run separately from the project root. These steps create an English slide deck, SVGs, narration, and audio files:

```powershell
.\.venv\Scripts\python.exe .\src\start_pro\start_query.py "How do solar panels work?" --out .\src\start_pro\paragraph.txt
Get-Content -Raw .\src\start_pro\paragraph.txt | .\.venv\Scripts\python.exe .\src\image_create\search_structure.py --format slides-json --out .\src\image_create\slides.json
.\.venv\Scripts\python.exe .\src\image_create\image_get.py .\src\image_create\slides.json --out .\src\image_create\slides_svg
.\.venv\Scripts\python.exe .\src\voice_over\speech.py .\src\image_create\slides.json --no-cover --out .\src\voice_over\speech.json
.\.venv\Scripts\python.exe .\src\voice_over\tts.py .\src\voice_over\speech.json --out .\src\voice_over\audio
```

Generate Hindi narration and audio from the English narration JSON:

```powershell
.\.venv\Scripts\python.exe .\src\voice_over\htts.py .\src\voice_over\speech.json --text-out .\src\voice_over\speech_hi.json --out .\src\voice_over\audio_hi
```

To assemble the saved SVG and audio files into a PowerPoint, install the Playwright Chromium browser once:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Then build a deck with the language-specific audio:

```powershell
.\.venv\Scripts\python.exe .\src\start_pro\concanate.py --lang en
.\.venv\Scripts\python.exe .\src\start_pro\concanate.py --lang hi
```

PowerPoint files are written to `src/start_pro/ppt_outputs/`. Chromium is needed for this SVG-to-PowerPoint image-rendering workflow; it is not required just to run the web app.

For macOS/Linux, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe` and replace PowerShell's `Get-Content -Raw file |` with `cat file |` for the slide-structuring step.

## Project map

```text
src/
  backend/main.py             FastAPI app, slide API, audio serving, cache, static app
  frontend/                   Vanilla JavaScript app, styles, and theme-specific logos
  start_pro/                  Query-to-English-paragraph service and PowerPoint assembly
  image_create/               Paragraph-to-slide structuring and SVG rendering
  voice_over/speech.py        English narration generation
  voice_over/tts.py           English MP3 generation
  voice_over/htts.py          Hindi translation and Hindi MP3 generation
```

Web request flow:

```text
Browser topic + narration language
  -> POST /api/generate
  -> One Cloudflare Workers AI request: direct topic -> slide structure + narration
  -> Hindi narration is generated in the same request when selected
  -> English slide JSON + narration text
  -> Browser slide player generates audio with Puter.js
```

The API caches slide responses by normalized query and narration language in `.eduvibe_slide_cache.sqlite3` locally, or Neon Postgres when `DATABASE_URL` is set. Browser-generated Puter audio is not stored by the backend. Guest chat history stays in browser local storage; signed-in account history is stored in the shared account database (Neon on Vercel) and can be restored across devices. Cold slide generation now uses one model request rather than serial paragraph, slide-structuring, and narration requests. The existing `/api/ppt` routes build PowerPoint files from the saved SVG/audio inputs used by the command-line presentation pipeline.

## Troubleshooting

- **The page opens, but searches fail:** check the project-root `.env` for the required Cloudflare values, confirm the token can use Workers AI, and inspect the Uvicorn terminal for the API error.
- **Google sign-in fails:** check `GOOGLE_CLIENT_ID`, authorized JavaScript origins, OAuth consent-screen settings, and that the backend was restarted.
- **Signed-in history does not load on Vercel:** set `DATABASE_URL` to the Neon Postgres connection string in the Vercel project's Environment Variables and redeploy. Account history cannot persist in a Vercel function's local filesystem.
- **Web narration fails:** check internet access to the Puter.js SDK and whether Puter sign-in or usage authorization is required.
- **Hindi narration fails:** check Cloudflare access for translation, then confirm Puter TTS is available in the browser.
- **Command-line audio fails:** check internet access to gTTS; retry later if requests are rate-limited.
- **No sound:** check browser tab/device volume and allow audio playback; try another supported browser.
- **PowerPoint export cannot render SVG:** run `python -m playwright install chromium` using the same virtual environment as the app.
- **Port 8000 is already in use:** start Uvicorn on another port, for example `python -m uvicorn backend.main:app --app-dir src --reload --port 8001`, and open the matching URL.
- **Python command is not found on Windows:** install Python and use the `py -3` launcher to create the virtual environment. Then run Python commands through `.venv\Scripts\python.exe`.

## Notes

- The account menu uses Google sign-in. Puter authorization, if requested, is separate and used only by the TTS service.
- Guest history is local to the browser. Signed-in history is stored in the configured account database and syncs anywhere the same account signs in.
- Keep credentials, audio caches, and generated files private when sharing or deploying the project.
