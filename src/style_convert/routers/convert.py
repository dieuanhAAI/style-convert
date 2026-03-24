import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from style_convert.core.config import Settings
from style_convert.core.exceptions import (
    ConvertioServiceError,
    ConvertioTimeoutError,
    LlmImageTooLargeError,
    LlmServiceError,
    StyleConvertError,
)
from style_convert.schemas.convert import ConvertFormFields
from style_convert.services import convertio_service, llm_service
from style_convert.utils.image import is_allowed_image_mime, resolve_upload_mime
from style_convert.utils.pipeline_debug import save_llm_png_to_dir

router = APIRouter()


def _effective_llm_provider(
    form_value: str | None,
    settings: Settings,
) -> Literal["openai", "anthropic"]:
    """Use form value when provided; otherwise ``Settings.llm_provider`` (from env)."""
    if form_value is None:
        return settings.llm_provider
    s = form_value.strip().lower()
    if not s:
        return settings.llm_provider
    if s not in ("openai", "anthropic"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="llm_provider must be 'openai' or 'anthropic'.",
        )
    return s  # type: ignore[return-value]


async def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    data = await upload.read()
    mime = resolve_upload_mime(upload.content_type, upload.filename, data)
    if not is_allowed_image_mime(mime):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing image type; only jpg/png allowed.",
        )
    assert mime is not None
    return data, mime


@router.post("/convert")
async def convert(
    style_reference: UploadFile = File(..., description="Style source image."),
    target_image: UploadFile = File(..., description="Image to transform."),
    prompt: str = Form(..., description="Style transfer instructions."),
    llm_provider: str | None = Form(
        None,
        description="Vision provider for this request: openai or anthropic. "
        "Omit to use server default (LLM_PROVIDER).",
    ),
) -> Response:
    """
    Full pipeline: multimodal prompt (OpenAI or Anthropic), PNG via OpenAI Images, then `.ai`
    via Convertio.
    """
    ConvertFormFields(prompt=prompt)

    try:
        style_bytes, style_mime = await _read_upload(style_reference)
        target_bytes, target_mime = await _read_upload(target_image)
    except HTTPException:
        raise

    from style_convert.core.config import get_settings_cached

    settings = get_settings_cached()
    provider = _effective_llm_provider(llm_provider, settings)

    artifact_id = uuid.uuid4().hex
    try:
        png_bytes = await llm_service.apply_style(
            settings,
            style_bytes,
            style_mime,
            target_bytes,
            target_mime,
            prompt,
            llm_provider=provider,
        )
        save_llm_png_to_dir(settings.save_intermediate_png_dir, png_bytes, artifact_id)
        ai_bytes = await convertio_service.png_bytes_to_ai(settings, png_bytes)
    except ConvertioTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Convertio conversion timed out.",
        ) from e
    except LlmImageTooLargeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except LlmServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM service error: {e}",
        ) from e
    except ConvertioServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Convertio error: {e}",
        ) from e
    except StyleConvertError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    filename = f"output_{artifact_id}.ai"
    return Response(
        content=ai_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
