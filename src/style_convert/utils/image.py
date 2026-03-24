import base64
from io import BytesIO

ALLOWED_IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png")

# Anthropic hard cap per image (decoded bytes). Stay slightly under to avoid edge rejections.
ANTHROPIC_MAX_IMAGE_BYTES = 5 * 1024 * 1024
ANTHROPIC_SAFE_IMAGE_BYTES = ANTHROPIC_MAX_IMAGE_BYTES - 256 * 1024


def bytes_to_base64_data_url(data: bytes, mime_type: str) -> str:
    """Build a data URL suitable for multimodal LLM payloads."""
    b64 = base64.standard_b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def guess_mime_from_upload(content_type: str | None, filename: str | None) -> str | None:
    """
    Best-effort MIME from upload metadata. Returns None if unknown.
    Prefer client Content-Type when present and allowed.
    """
    if content_type and any(content_type.lower().startswith(p) for p in ALLOWED_IMAGE_MIME_PREFIXES):
        return content_type.split(";", 1)[0].strip().lower()

    if not filename:
        return None
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    return None


def is_allowed_image_mime(mime: str | None) -> bool:
    if not mime:
        return False
    return any(mime.lower().startswith(p) for p in ALLOWED_IMAGE_MIME_PREFIXES)


def mime_from_magic_bytes(data: bytes) -> str | None:
    """Detect image MIME from magic bytes (first bytes of the file)."""
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return None


def resolve_upload_mime(content_type: str | None, filename: str | None, data: bytes) -> str | None:
    """Resolve MIME for an upload using headers, filename, then magic bytes."""
    mime = guess_mime_from_upload(content_type, filename)
    if is_allowed_image_mime(mime):
        return mime
    return mime_from_magic_bytes(data)


def _pil_to_rgb(image: "Image.Image") -> "Image.Image":
    from PIL import Image

    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    if image.mode == "P":
        return image.convert("RGBA").convert("RGB")
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def clamp_image_bytes_for_anthropic(data: bytes, mime: str) -> tuple[bytes, str]:
    """
    Ensure image payload is within Anthropic's per-image byte limit by re-encoding as JPEG
    and downscaling if needed. Large PNGs are typically shrunk substantially.

    Uses a sub-5 MiB target so resized outputs are not rejected at the API boundary.

    Returns ``(bytes, media_type)`` — MIME becomes ``image/jpeg`` when re-encoded.
    Raises ``ValueError`` if the image cannot be made to fit.
    """
    if len(data) <= ANTHROPIC_SAFE_IMAGE_BYTES:
        return data, mime

    from PIL import Image

    def encode_jpeg(img: Image.Image, quality: int) -> bytes:
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    try:
        im = _pil_to_rgb(Image.open(BytesIO(data)))
    except OSError as e:
        raise ValueError(f"Could not read image for resizing: {e}") from e
    im.load()
    current = im
    quality = 90
    limit = ANTHROPIC_SAFE_IMAGE_BYTES

    for _ in range(160):
        out = encode_jpeg(current, quality)
        if len(out) <= limit:
            return out, "image/jpeg"

        w, h = current.size
        mx = max(w, h)
        # Always shrink by area when still over budget — avoids thin strips where min(w,h)
        # is small but the long edge (and JPEG size) stays huge.
        if mx > 48:
            scale = 0.87
            nw = max(int(w * scale), 1)
            nh = max(int(h * scale), 1)
            if nw >= w and nh >= h:
                nw, nh = max(w - 1, 1), max(h - 1, 1)
            current = current.resize((nw, nh), Image.Resampling.LANCZOS)
            continue

        quality = max(20, quality - 10)
        if quality <= 20:
            break

    raise ValueError(
        "Image could not be compressed below Anthropic's 5 MB per-image limit; "
        "try a smaller source file.",
    )
