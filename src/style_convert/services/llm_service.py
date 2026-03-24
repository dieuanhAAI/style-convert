import base64
from typing import Literal

from anthropic import APIError as AnthropicAPIError
from anthropic import AsyncAnthropic
from openai import APIError as OpenAIAPIError
from openai import AsyncOpenAI

from style_convert.core.config import Settings
from style_convert.core.exceptions import LlmImageTooLargeError, LlmServiceError
from style_convert.utils.image import (
    bytes_to_base64_data_url,
    clamp_image_bytes_for_anthropic,
)

_VISION_SYSTEM = (
    "You write prompts for image generation. Be specific about palette, lighting, texture, "
    "and line quality from the style reference. Keep the target image's subject, pose, "
    "layout, and composition unless the user explicitly asks to change them."
)


def _user_instruction_block(prompt: str) -> str:
    return (
        "Image 1: STYLE reference (look and feel to borrow).\n"
        "Image 2: TARGET (content and composition to preserve).\n\n"
        f"User instructions:\n{prompt}\n\n"
        "Output a single detailed English image-generation prompt only. "
        "No labels, markdown, or quotes."
    )


def _openai_client(settings: Settings) -> AsyncOpenAI:
    kwargs: dict = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return AsyncOpenAI(**kwargs)


def _anthropic_client(settings: Settings) -> AsyncAnthropic:
    kwargs: dict = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return AsyncAnthropic(**kwargs)


def _is_anthropic_image_payload_too_large(exc: AnthropicAPIError) -> bool:
    """Detect Anthropic 400 invalid_request_error for per-image byte / base64 limits."""
    parts: list[str] = [getattr(exc, "message", None) or str(exc)]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts.append(str(err.get("message", "")))
        parts.append(str(body))
    blob = " ".join(parts).lower()
    if "5242880" in blob:
        return True
    if ("5 mb" in blob or "5mb" in blob) and ("image" in blob or "base64" in blob):
        return True
    if "exceeds" in blob and "maximum" in blob and ("image" in blob or "base64" in blob):
        return True
    return False


_LLM_IMAGE_TOO_LARGE_HINT = (
    "Anthropic allows at most about 5 MB per image. That limit was exceeded for at least one "
    "upload (even after automatic resizing). Use smaller or lower-resolution JPEG/PNG files, or "
    "choose OpenAI as the vision provider."
)


async def _synthesize_image_prompt_openai(
    settings: Settings,
    style_reference: bytes,
    style_mime: str,
    target_image: bytes,
    target_mime: str,
    prompt: str,
) -> str:
    style_url = bytes_to_base64_data_url(style_reference, style_mime)
    target_url = bytes_to_base64_data_url(target_image, target_mime)
    user_text = _user_instruction_block(prompt)
    client = _openai_client(settings)

    try:
        completion = await client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[
                {"role": "system", "content": _VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": style_url}},
                        {"type": "image_url", "image_url": {"url": target_url}},
                    ],
                },
            ],
            max_tokens=1200,
        )
    except OpenAIAPIError as e:
        raise LlmServiceError(str(e)) from e

    image_prompt = (completion.choices[0].message.content or "").strip()
    if not image_prompt:
        raise LlmServiceError("Vision model returned an empty prompt.")
    return image_prompt[:4000]


async def _synthesize_image_prompt_anthropic(
    settings: Settings,
    style_reference: bytes,
    style_mime: str,
    target_image: bytes,
    target_mime: str,
    prompt: str,
) -> str:
    try:
        style_clamped, style_mt = clamp_image_bytes_for_anthropic(style_reference, style_mime)
        target_clamped, target_mt = clamp_image_bytes_for_anthropic(target_image, target_mime)
    except ValueError as e:
        raise LlmImageTooLargeError(str(e)) from e

    style_b64 = base64.standard_b64encode(style_clamped).decode("ascii")
    target_b64 = base64.standard_b64encode(target_clamped).decode("ascii")
    user_text = _user_instruction_block(prompt)
    client = _anthropic_client(settings)

    try:
        message = await client.messages.create(
            model=settings.anthropic_vision_model,
            max_tokens=1200,
            system=_VISION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": style_mt,
                                "data": style_b64,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": target_mt,
                                "data": target_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except AnthropicAPIError as e:
        if _is_anthropic_image_payload_too_large(e):
            raise LlmImageTooLargeError(_LLM_IMAGE_TOO_LARGE_HINT) from e
        raise LlmServiceError(str(e)) from e

    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    image_prompt = "".join(parts).strip()
    if not image_prompt:
        raise LlmServiceError("Anthropic model returned an empty prompt.")
    return image_prompt[:4000]


async def _generate_png_from_prompt(settings: Settings, image_prompt: str) -> bytes:
    client = _openai_client(settings)
    try:
        img_response = await client.images.generate(
            model=settings.openai_image_model,
            prompt=image_prompt,
            size=settings.openai_image_size,  # type: ignore[arg-type]
            response_format="b64_json",
            n=1,
        )
    except OpenAIAPIError as e:
        raise LlmServiceError(str(e)) from e

    if not img_response.data:
        raise LlmServiceError("Image model returned no data.")
    b64 = img_response.data[0].b64_json
    if not b64:
        raise LlmServiceError("Image model returned no image (b64_json missing).")
    return base64.standard_b64decode(b64)


async def apply_style(
    settings: Settings,
    style_reference: bytes,
    style_mime: str,
    target_image: bytes,
    target_mime: str,
    prompt: str,
    *,
    llm_provider: Literal["openai", "anthropic"] | None = None,
) -> bytes:
    """
    Multimodal model (OpenAI or Anthropic) produces an image-generation prompt;
    OpenAI Images returns PNG bytes (in-memory; no disk).

    Pass ``llm_provider`` to override ``Settings.llm_provider`` for this call (e.g. from the web UI).

    Anthropic does not expose raster output on the Messages API, so DALL·E (or another
    configured OpenAI image model) is always used for the final PNG. Set OPENAI_API_KEY.
    """
    if not settings.openai_api_key.strip():
        raise LlmServiceError("OPENAI_API_KEY is required for image generation (PNG output).")

    provider: Literal["openai", "anthropic"] = (
        llm_provider if llm_provider is not None else settings.llm_provider
    )
    if provider == "anthropic" and not settings.anthropic_api_key.strip():
        raise LlmServiceError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")

    if provider == "openai":
        image_prompt = await _synthesize_image_prompt_openai(
            settings,
            style_reference,
            style_mime,
            target_image,
            target_mime,
            prompt,
        )
    elif provider == "anthropic":
        image_prompt = await _synthesize_image_prompt_anthropic(
            settings,
            style_reference,
            style_mime,
            target_image,
            target_mime,
            prompt,
        )
    else:
        raise LlmServiceError(f"Unknown llm_provider: {provider!r}.")

    return await _generate_png_from_prompt(settings, image_prompt)
