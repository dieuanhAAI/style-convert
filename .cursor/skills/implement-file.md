---
name: implement-file
description: Implement a FastAPI file (service, router, schema, config, or utility) for the style-convert project following stateless service conventions, in-memory image handling, Claude API and Convertio API integration patterns. Use when creating or filling in any source file, implementing a feature, or when the user asks to build, implement, or scaffold a module.
---

# Implement File

## Context

The style-convert project uses:
- **FastAPI** for routing and dependency injection
- **Claude API** (via `anthropic` SDK) for multimodal style transfer — takes two images + prompt, returns a styled PNG
- **Convertio API** (via `requests`) for PNG → `.ai` conversion with polling
- **Pydantic v2** for request validation and settings management
- All image data is handled in-memory as `bytes` — never written to disk
- Services are stateless — no database, no session, no shared state
- Business logic lives in services — the router is thin
- API keys are loaded exclusively from `core/config.py` via `pydantic-settings`
- Exceptions: `HTTPException` with status codes `400`, `502`, `504`
- `502` — external API call failed (Claude or Convertio)
- `504` — Convertio polling exceeded timeout

## Task

Read the target file context, identify which file type is being implemented, then generate a complete, production-ready implementation following the project's conventions.

## Steps

1. **Identify the file type** being implemented:
   - `service` — stateless class wrapping an external API (`llm_service`, `convertio_service`)
   - `router` — thin FastAPI route that calls services in order and returns a file response
   - `schema` — Pydantic models for request validation
   - `config` — `pydantic-settings` class for environment variable loading
   - `utility` — helper functions (e.g. base64 encoding, MIME type detection)

2. **Read related files** before writing:
   - For the router: read both services and schemas first
   - For `llm_service`: read `utils/image.py` and `core/config.py` first
   - For `convertio_service`: read `core/config.py` first
   - Never assume API response shapes — derive from the real API structure

3. **Apply pipeline conventions**:
   - `llm_service.apply_style(style_ref: bytes, target: bytes, prompt: str) → bytes` — always returns PNG bytes
   - `convertio_service.convert(png_bytes: bytes) → bytes` — always returns `.ai` bytes
   - Router passes `llm_service` output directly into `convertio_service` — never re-read from disk
   - File type validation (jpg/png only) happens in the router before any service is called

4. **Write the file** completely — no placeholders, no `pass`, no `# TODO`

## Output Format

### Service — LLM (`services/llm_service.py`)

```python
import base64
import anthropic
from fastapi import HTTPException

from app.core.config import settings


class LLMService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def apply_style(self, style_reference: bytes, target_image: bytes, prompt: str) -> bytes:
        try:
            response = self.client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": base64.b64encode(style_reference).decode(),
                                },
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": base64.b64encode(target_image).decode(),
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            # extract PNG bytes from response
            image_block = next(b for b in response.content if b.type == "image")
            return image_block.source.data
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM API error: {str(e)}")
```

### Service — Convertio (`services/convertio_service.py`)

```python
import time
import requests
from fastapi import HTTPException

from app.core.config import settings

POLL_INTERVAL = 3   # seconds between status checks
MAX_POLLS = 20      # 504 after MAX_POLLS * POLL_INTERVAL seconds


class ConvertioService:
    BASE_URL = "https://api.convertio.co/convert"

    def convert(self, png_bytes: bytes) -> bytes:
        job_id = self._upload(png_bytes)
        output_url = self._poll(job_id)
        return self._download(output_url)

    def _upload(self, png_bytes: bytes) -> str:
        response = requests.post(
            self.BASE_URL,
            json={
                "apikey": settings.convertio_api_key,
                "input": "raw",
                "file": png_bytes.hex(),
                "filename": "output.png",
                "outputformat": "ai",
            },
        )
        data = response.json()
        if response.status_code != 200 or data.get("status") != "ok":
            raise HTTPException(status_code=502, detail="Convertio upload failed")
        return data["data"]["id"]

    def _poll(self, job_id: str) -> str:
        for _ in range(MAX_POLLS):
            response = requests.get(f"{self.BASE_URL}/{job_id}/status")
            data = response.json()
            status = data["data"]["step"]
            if status == "finish":
                return data["data"]["output"]["url"]
            if status == "error":
                raise HTTPException(status_code=502, detail="Convertio conversion failed")
            time.sleep(POLL_INTERVAL)
        raise HTTPException(status_code=504, detail="Convertio conversion timed out")

    def _download(self, url: str) -> bytes:
        response = requests.get(url)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to download converted file")
        return response.content
```

### Router (`routers/convert.py`)

```python
import uuid
from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import Response

from app.services.llm_service import LLMService
from app.services.convertio_service import ConvertioService

router = APIRouter()
llm_service = LLMService()
convertio_service = ConvertioService()

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg"}


@router.post("/convert")
async def convert(
    style_reference: UploadFile = File(...),
    target_image: UploadFile = File(...),
    prompt: str = Form(...),
):
    _validate_image(style_reference)
    _validate_image(target_image)

    style_bytes = await style_reference.read()
    target_bytes = await target_image.read()

    png_bytes = llm_service.apply_style(style_bytes, target_bytes, prompt)
    ai_bytes = convertio_service.convert(png_bytes)

    filename = f"output_{uuid.uuid4().hex}.ai"
    return Response(
        content=ai_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _validate_image(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Only PNG and JPEG are accepted.",
        )
```

### Config (`core/config.py`)

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    convertio_api_key: str

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

### Utility (`utils/image.py`)

```python
import base64


def to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to a base64 string for API payloads."""
    return base64.b64encode(image_bytes).decode("utf-8")


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "application/octet-stream"
```

## Quality Checklist
- [ ] No image data is written to disk — all bytes stay in memory throughout the pipeline
- [ ] `llm_service.apply_style` output is passed directly into `convertio_service.convert` — no re-encoding
- [ ] File type validation happens in the router before any service method is called
- [ ] All API keys are read from `settings` — never hardcoded
- [ ] `502` is raised for any external API failure (Claude or Convertio)
- [ ] `504` is raised only for Convertio polling timeout, not for other errors
- [ ] Convertio polling has a finite loop with a configurable max — never a `while True`
- [ ] Router returns a `Response` with `application/octet-stream` and a `Content-Disposition` attachment header
- [ ] Output filename includes a UUID to prevent collisions
- [ ] Services are stateless — no instance variables mutated between requests
- [ ] File is complete — no `pass`, no `# TODO`, no placeholder methods