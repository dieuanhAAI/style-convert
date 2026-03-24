# style-convert

REST API that takes a **style reference** image, a **target** image, and a text **prompt**, produces a styled raster image (PNG) via **OpenAI or Anthropic** (vision) plus **OpenAI Images**, then converts that PNG to an Adobe Illustrator **`.ai`** file using the **Convertio** API. By default the pipeline keeps images **in memory** only. For local testing you can optionally **save the LLM PNG** to disk (see `SAVE_INTERMEDIATE_PNG_DIR` below).

## Requirements

- Python **3.11+**
- API keys:
  - **OpenAI** — required for image generation (PNG) in all modes; also used for vision when `LLM_PROVIDER=openai`
  - **Anthropic** — required only when `LLM_PROVIDER=anthropic`
  - **Convertio** — required for PNG → `.ai`

## Setup

```bash
cd convert-style-app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Create a `.env` file in `convert-style-app` (same directory as this README). Pydantic loads it automatically when the app runs from that directory.

Example:

```env
# Vision + image pipeline
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=          # optional (e.g. proxies / Azure-compatible endpoints)
# OPENAI_VISION_MODEL=gpt-4o
# OPENAI_IMAGE_MODEL=dall-e-3
# OPENAI_IMAGE_SIZE=1024x1024

# If LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_VISION_MODEL=claude-sonnet-4-20250514

# Convertio (PNG → .ai)
CONVERTIO_API_KEY=...
# CONVERTIO_BASE_URL=https://api.convertio.co
# CONVERTIO_POLL_TIMEOUT_SECONDS=300
# CONVERTIO_POLL_INTERVAL_SECONDS=2

# Optional: save LLM PNG per request for debugging (same id as downloaded .ai filename)
# SAVE_INTERMEDIATE_PNG_DIR=./debug_pipeline
```

**Note:** With `LLM_PROVIDER=anthropic`, Claude builds the text prompt for the image generator; **OpenAI Images** still produces the PNG, so **`OPENAI_API_KEY` remains required**. Anthropic allows at most **5 MB per image**; larger uploads are automatically re-encoded and downscaled before the API call (transparent PNGs are flattened onto white when converted to JPEG).

### Intermediate PNG on disk (testing)

If **`SAVE_INTERMEDIATE_PNG_DIR`** is set (e.g. `./debug_pipeline`), after a successful LLM step the server writes **`llm_styled_<artifact_id>.png`** into that folder. The browser download uses **`output_<artifact_id>.ai`** with the **same** `artifact_id` so you can match PNG and `.ai` for a given run. The directory is created if needed; if writing fails, a warning is logged and the API still returns the `.ai` file when conversion succeeds.

## Run

From `convert-style-app`:

```bash
uvicorn main:app --app-dir src --reload
```

- **Web UI:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/) — same fields as `POST /convert`; submits via `fetch` and triggers an `.ai` download in the browser.
- **OpenAPI docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## API

### `POST /convert`

**Content-Type:** `multipart/form-data`

| Field              | Type   | Required | Description                          |
|--------------------|--------|----------|--------------------------------------|
| `style_reference`  | file   | yes      | Style source (JPEG or PNG)           |
| `target_image`     | file   | yes      | Image to transform (JPEG or PNG)     |
| `prompt`           | string | yes      | Instructions (1–8000 characters)     |
| `llm_provider`     | string | no       | `openai` or `anthropic`; per-request vision model. Omit to use `LLM_PROVIDER` from env. |

**Success:** `200` with body `application/octet-stream` (binary `.ai`).  
Header: `Content-Disposition: attachment; filename="output_<uuid>.ai"`

**Errors (typical):**

| Status | Meaning                                              |
|--------|------------------------------------------------------|
| `400`  | Missing/invalid image type, invalid `llm_provider`, or image too large for Anthropic (after resizing) |
| `422`  | Validation error (e.g. empty `prompt`)               |
| `502`  | LLM or Convertio / upstream failure                  |
| `504`  | Convertio conversion exceeded poll timeout           |

### Example (`curl`)

```bash
curl -sS -X POST "http://127.0.0.1:8000/convert" \
  -F "style_reference=@/path/to/style.png" \
  -F "target_image=@/path/to/target.jpg" \
  -F "prompt=Apply the illustration style to the photo while keeping the composition." \
  -F "llm_provider=anthropic" \
  -o output.ai
```

## Project layout

```
src/
├── main.py                      # FastAPI app, static mount, GET /
├── style_convert/
│   ├── static/                  # Web UI (index.html, styles, script)
│   ├── routers/convert.py      # POST /convert
│   ├── services/
│   │   ├── llm_service.py      # Vision + OpenAI Images → PNG
│   │   └── convertio_service.py
│   ├── schemas/convert.py
│   ├── core/config.py          # Settings from environment
│   └── utils/image.py
```

## Development extras

```bash
pip install -e ".[dev]"
```

## Git and GitHub

This repo follows branch conventions documented in `.cursor/rules/git-repo-init.mdc`:

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code |
| `develop` | Integration branch for ongoing work |

`.env` and `.venv/` are gitignored.

**Create the remote and push** (after [GitHub CLI](https://cli.github.com/) login: `gh auth login`):

```bash
gh repo create style-convert --private --source=. --remote=origin --push
git push -u origin main
git push -u origin develop
```

If `main` was already pushed by `gh repo create --push`, only push `develop` if it is not on the remote yet:

```bash
git checkout develop
git push -u origin develop
```

Without `gh`, create an empty private repo named `style-convert` on GitHub, then:

```bash
git remote add origin https://github.com/YOUR_USER/style-convert.git
git push -u origin main
git push -u origin develop
```

---

Convertio is a third-party service; see their [API documentation](https://developers.convertio.co/api/docs) for quotas and behavior.
