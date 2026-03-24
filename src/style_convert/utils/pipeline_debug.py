"""Optional on-disk artifacts for local testing (off by default)."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def save_llm_png_to_dir(directory: str | None, png_bytes: bytes, artifact_id: str) -> None:
    """
    If ``directory`` is set, write ``png_bytes`` to ``{directory}/llm_styled_{artifact_id}.png``.

    Creates the directory if needed. On ``OSError``, logs a warning and does not raise (pipeline
    still returns the `.ai` response).
    """
    if not directory or not str(directory).strip():
        return
    root = Path(str(directory).strip()).expanduser().resolve()
    path = root / f"llm_styled_{artifact_id}.png"
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes)
    except OSError as e:
        logger.warning("Could not save intermediate PNG to %s: %s", path, e)
