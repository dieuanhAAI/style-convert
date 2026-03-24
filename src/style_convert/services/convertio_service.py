import asyncio
import base64
from typing import Any

import httpx

from style_convert.core.config import Settings
from style_convert.core.exceptions import ConvertioServiceError, ConvertioTimeoutError


def _root(settings: Settings) -> str:
    return settings.convertio_base_url.rstrip("/")


def _expect_ok(body: dict[str, Any], context: str) -> dict[str, Any]:
    if body.get("status") == "error":
        msg = str(body.get("error", "unknown error"))
        raise ConvertioServiceError(f"{context}: {msg}")
    if body.get("status") != "ok":
        raise ConvertioServiceError(f"{context}: unexpected response status {body.get('status')!r}.")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ConvertioServiceError(f"{context}: missing data object.")
    return data


async def _start_conversion(client: httpx.AsyncClient, settings: Settings, png_bytes: bytes) -> str:
    payload = {
        "apikey": settings.convertio_api_key,
        "input": "base64",
        "file": base64.standard_b64encode(png_bytes).decode("ascii"),
        "filename": "styled.png",
        "outputformat": "ai",
    }
    try:
        response = await client.post(f"{_root(settings)}/convert", json=payload)
    except httpx.RequestError as e:
        raise ConvertioServiceError(f"Convertio upload request failed: {e}") from e

    try:
        body = response.json()
    except ValueError as e:
        raise ConvertioServiceError(f"Convertio upload invalid JSON (HTTP {response.status_code}).") from e

    if not isinstance(body, dict):
        raise ConvertioServiceError(f"Convertio upload unexpected JSON (HTTP {response.status_code}).")

    if response.status_code != 200:
        err = body.get("error", response.text)
        raise ConvertioServiceError(f"Convertio upload HTTP {response.status_code}: {err}")

    data = _expect_ok(body, "upload")
    job_id = data.get("id")
    if not job_id or not isinstance(job_id, str):
        raise ConvertioServiceError("Convertio upload response missing conversion id.")
    return job_id


async def _poll_status(client: httpx.AsyncClient, settings: Settings, job_id: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(settings.convertio_poll_timeout_seconds)
    interval = float(settings.convertio_poll_interval_seconds)

    while True:
        if loop.time() >= deadline:
            raise ConvertioTimeoutError("Convertio conversion exceeded poll timeout.")

        try:
            response = await client.get(f"{_root(settings)}/convert/{job_id}/status")
        except httpx.RequestError as e:
            raise ConvertioServiceError(f"Convertio status request failed: {e}") from e

        try:
            body = response.json()
        except ValueError as e:
            raise ConvertioServiceError(f"Convertio status invalid JSON (HTTP {response.status_code}).") from e

        if not isinstance(body, dict):
            raise ConvertioServiceError(
                f"Convertio status unexpected JSON (HTTP {response.status_code}).",
            )

        if body.get("status") == "error":
            raise ConvertioServiceError(str(body.get("error", "Convertio status error")))

        if response.status_code != 200:
            raise ConvertioServiceError(f"Convertio status HTTP {response.status_code}: {body.get('error', body)!r}")

        data = _expect_ok(body, "status")
        step = data.get("step")
        if step == "finish":
            return
        if step not in ("wait", "convert", "upload", None):
            raise ConvertioServiceError(f"Convertio unexpected step: {step!r}.")

        await asyncio.sleep(interval)


async def _download_result_base64(client: httpx.AsyncClient, settings: Settings, job_id: str) -> bytes:
    try:
        response = await client.get(f"{_root(settings)}/convert/{job_id}/dl/base64")
    except httpx.RequestError as e:
        raise ConvertioServiceError(f"Convertio download request failed: {e}") from e

    try:
        body = response.json()
    except ValueError as e:
        raise ConvertioServiceError(f"Convertio download invalid JSON (HTTP {response.status_code}).") from e

    if not isinstance(body, dict):
        raise ConvertioServiceError(f"Convertio download unexpected JSON (HTTP {response.status_code}).")

    if body.get("status") == "error":
        raise ConvertioServiceError(str(body.get("error", "Convertio download error")))

    if response.status_code != 200:
        raise ConvertioServiceError(f"Convertio download HTTP {response.status_code}: {body.get('error', body)!r}")

    data = _expect_ok(body, "download")
    raw = data.get("content")
    if not raw or not isinstance(raw, str):
        raise ConvertioServiceError("Convertio download missing base64 content.")
    try:
        return base64.standard_b64decode(raw)
    except (ValueError, TypeError) as e:
        raise ConvertioServiceError(f"Convertio download invalid base64: {e}") from e


async def png_bytes_to_ai(settings: Settings, png_bytes: bytes) -> bytes:
    """
    Start a PNG → AI job on Convertio, poll until finished, return `.ai` bytes in memory.
    """
    if not settings.convertio_api_key.strip():
        raise ConvertioServiceError("CONVERTIO_API_KEY is not set.")

    timeout = httpx.Timeout(
        connect=30.0,
        read=max(60.0, settings.convertio_poll_timeout_seconds + 30.0),
        write=60.0,
        pool=30.0,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        job_id = await _start_conversion(client, settings, png_bytes)
        await _poll_status(client, settings, job_id)
        return await _download_result_base64(client, settings, job_id)
