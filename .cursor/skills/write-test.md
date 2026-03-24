---
name: write-test
description: Generate comprehensive pytest unit tests for style-convert services and routers with mocked Claude API and Convertio API calls, in-memory image handling, and pipeline error coverage. Use when writing tests, creating test files, or when the user mentions unit testing, test coverage, or service tests.
---

# Write Test

## Context

The style-convert project uses:
- **pytest** for unit testing
- **unittest.mock** (`MagicMock`, `AsyncMock`, `patch`) to mock Claude API and Convertio API calls
- Services are stateless — no DB, no session injection
- All image data is handled in-memory as `bytes` — no disk I/O
- The router is thin — business logic lives entirely in `llm_service` and `convertio_service`
- Exceptions: `HTTPException` with status codes `400`, `502`, `504`
- `llm_service` and `convertio_service` are independently testable
- API keys are never hardcoded — loaded from `core/config.py`

## Task

Read the target file, identify whether it is a service or router, then generate comprehensive pytest tests covering the happy path, API failure cases, timeout cases, and input validation.

## Steps

1. **Read the target file** and identify:
   - All public methods
   - External API calls being made (Claude API or Convertio API)
   - Exception types being raised and their trigger conditions
   - Any input validation logic

2. **Analyze each method** to determine test cases:
   - Happy path (valid inputs, APIs respond successfully)
   - External API failure (LLM or Convertio returns an error → `502`)
   - Timeout case (Convertio polling exceeds limit → `504`)
   - Invalid input (wrong file type, missing field → `400`)
   - Verify no disk I/O occurs — all image data stays as `bytes`

3. **Design test data**:
   - Use minimal synthetic `bytes` objects as fake image payloads (e.g. `b"fake-png-bytes"`)
   - Use fixed UUIDs or filenames for output assertions
   - Mock API responses to match the real response shape of Claude and Convertio

4. **Write tests** organized by class per method or service

## Output Format

Create a test file at the corresponding path (replace `.py` with `_test.py`):

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app

# ─── Mock Data ──────────────────────────────────────────────────────

FAKE_STYLE_REF = b"fake-style-reference-bytes"
FAKE_TARGET_IMAGE = b"fake-target-image-bytes"
FAKE_PNG_OUTPUT = b"fake-png-output-bytes"
FAKE_AI_OUTPUT = b"fake-ai-output-bytes"
FAKE_PROMPT = "Apply a watercolor style to the target image"


# ─── LLMService Tests ────────────────────────────────────────────────

class TestLLMService:
    @patch("app.services.llm_service.anthropic.Anthropic")
    def test_returns_png_bytes_on_success(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="image", source=MagicMock(data=FAKE_PNG_OUTPUT))]
        )

        from app.services.llm_service import LLMService
        service = LLMService()
        result = service.apply_style(FAKE_STYLE_REF, FAKE_TARGET_IMAGE, FAKE_PROMPT)

        mock_client.messages.create.assert_called_once()
        assert isinstance(result, bytes)
        assert result == FAKE_PNG_OUTPUT

    @patch("app.services.llm_service.anthropic.Anthropic")
    def test_encodes_both_images_in_payload(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="image", source=MagicMock(data=FAKE_PNG_OUTPUT))]
        )

        from app.services.llm_service import LLMService
        service = LLMService()
        service.apply_style(FAKE_STYLE_REF, FAKE_TARGET_IMAGE, FAKE_PROMPT)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        message_content = call_kwargs["messages"][0]["content"]
        image_blocks = [b for b in message_content if b.get("type") == "image"]
        assert len(image_blocks) == 2

    @patch("app.services.llm_service.anthropic.Anthropic")
    def test_raises_502_on_api_error(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("Claude API unavailable")

        from app.services.llm_service import LLMService
        service = LLMService()

        with pytest.raises(HTTPException) as exc_info:
            service.apply_style(FAKE_STYLE_REF, FAKE_TARGET_IMAGE, FAKE_PROMPT)
        assert exc_info.value.status_code == 502

    @patch("app.services.llm_service.anthropic.Anthropic")
    def test_does_not_write_to_disk(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="image", source=MagicMock(data=FAKE_PNG_OUTPUT))]
        )

        from app.services.llm_service import LLMService
        with patch("builtins.open") as mock_open:
            service = LLMService()
            service.apply_style(FAKE_STYLE_REF, FAKE_TARGET_IMAGE, FAKE_PROMPT)
            mock_open.assert_not_called()


# ─── ConvertioService Tests ──────────────────────────────────────────

class TestConvertioService:
    @patch("app.services.convertio_service.requests.post")
    @patch("app.services.convertio_service.requests.get")
    def test_returns_ai_bytes_on_success(self, mock_get, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"job_id": "job-uuid-001"}}
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"status": "finished", "output": {"url": "https://cdn.convertio.co/output.ai"}}}
        )

        with patch("app.services.convertio_service.requests.get") as mock_download:
            mock_download.side_effect = [
                MagicMock(status_code=200, json=lambda: {"data": {"status": "finished", "output": {"url": "https://cdn.convertio.co/output.ai"}}}),
                MagicMock(status_code=200, content=FAKE_AI_OUTPUT),
            ]
            from app.services.convertio_service import ConvertioService
            service = ConvertioService()
            result = service.convert(FAKE_PNG_OUTPUT)

        assert isinstance(result, bytes)
        assert result == FAKE_AI_OUTPUT

    @patch("app.services.convertio_service.requests.post")
    def test_raises_502_when_upload_fails(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, json=lambda: {"error": "upload failed"})

        from app.services.convertio_service import ConvertioService
        service = ConvertioService()

        with pytest.raises(HTTPException) as exc_info:
            service.convert(FAKE_PNG_OUTPUT)
        assert exc_info.value.status_code == 502

    @patch("app.services.convertio_service.requests.post")
    @patch("app.services.convertio_service.requests.get")
    def test_raises_504_when_polling_times_out(self, mock_get, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"job_id": "job-uuid-001"}}
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"status": "processing"}}  # never finishes
        )

        from app.services.convertio_service import ConvertioService
        service = ConvertioService()

        with pytest.raises(HTTPException) as exc_info:
            service.convert(FAKE_PNG_OUTPUT)
        assert exc_info.value.status_code == 504

    @patch("app.services.convertio_service.requests.post")
    @patch("app.services.convertio_service.requests.get")
    def test_does_not_write_to_disk(self, mock_get, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"job_id": "job-uuid-001"}}
        )
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"data": {"status": "finished", "output": {"url": "https://cdn.convertio.co/output.ai"}}}),
            MagicMock(status_code=200, content=FAKE_AI_OUTPUT),
        ]

        from app.services.convertio_service import ConvertioService
        with patch("builtins.open") as mock_open:
            service = ConvertioService()
            service.convert(FAKE_PNG_OUTPUT)
            mock_open.assert_not_called()


# ─── Router Tests (/convert) ─────────────────────────────────────────

class TestConvertRouter:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @patch("app.routers.convert.llm_service")
    @patch("app.routers.convert.convertio_service")
    def test_returns_ai_file_on_success(self, mock_convertio, mock_llm, client):
        mock_llm.apply_style.return_value = FAKE_PNG_OUTPUT
        mock_convertio.convert.return_value = FAKE_AI_OUTPUT

        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )

        assert response.status_code == 200
        assert response.content == FAKE_AI_OUTPUT
        assert "attachment" in response.headers["content-disposition"]
        assert ".ai" in response.headers["content-disposition"]

    @patch("app.routers.convert.llm_service")
    @patch("app.routers.convert.convertio_service")
    def test_calls_services_in_order(self, mock_convertio, mock_llm, client):
        mock_llm.apply_style.return_value = FAKE_PNG_OUTPUT
        mock_convertio.convert.return_value = FAKE_AI_OUTPUT

        client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )

        mock_llm.apply_style.assert_called_once_with(FAKE_STYLE_REF, FAKE_TARGET_IMAGE, FAKE_PROMPT)
        mock_convertio.convert.assert_called_once_with(FAKE_PNG_OUTPUT)

    def test_raises_400_for_invalid_file_type(self, client):
        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.pdf", b"fake-pdf", "application/pdf"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )
        assert response.status_code == 400

    def test_raises_422_when_prompt_missing(self, client):
        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
        )
        assert response.status_code == 422

    def test_raises_422_when_file_missing(self, client):
        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )
        assert response.status_code == 422

    @patch("app.routers.convert.llm_service")
    @patch("app.routers.convert.convertio_service")
    def test_propagates_502_from_llm_service(self, mock_convertio, mock_llm, client):
        mock_llm.apply_style.side_effect = HTTPException(status_code=502, detail="LLM error")

        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )
        assert response.status_code == 502

    @patch("app.routers.convert.llm_service")
    @patch("app.routers.convert.convertio_service")
    def test_propagates_504_from_convertio_service(self, mock_convertio, mock_llm, client):
        mock_llm.apply_style.return_value = FAKE_PNG_OUTPUT
        mock_convertio.convert.side_effect = HTTPException(status_code=504, detail="Conversion timed out")

        response = client.post(
            "/convert",
            files={
                "style_reference": ("style.png", FAKE_STYLE_REF, "image/png"),
                "target_image": ("target.png", FAKE_TARGET_IMAGE, "image/png"),
            },
            data={"prompt": FAKE_PROMPT},
        )
        assert response.status_code == 504
```

## Quality Checklist
- [ ] `LLMService` tests verify both images are encoded and sent in the API payload
- [ ] `LLMService` tests assert `502` is raised on Claude API failure
- [ ] `ConvertioService` tests cover success, upload failure (`502`), and polling timeout (`504`)
- [ ] Router tests verify services are called in the correct order with the correct arguments
- [ ] Router tests assert the response is a binary `.ai` file with correct `Content-Disposition` header
- [ ] Invalid file type (non-image) returns `400` at the router level
- [ ] Missing fields return `422` before any service is called
- [ ] No `open()` calls occur in any test — all image data stays as `bytes`
- [ ] All external HTTP calls (`anthropic`, `requests`) are fully mocked — no real network calls
- [ ] API keys are never asserted on directly — config loading is not the service's concern
- [ ] Imports use `pytest` and `unittest.mock`, not any JS testing libraries