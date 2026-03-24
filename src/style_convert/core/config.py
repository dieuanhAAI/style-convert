from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API keys and tunables loaded from environment (see `.env` at project root)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["openai", "anthropic"] = Field(
        default="openai",
        description="Which model builds the image prompt from the two inputs. "
        "PNG rasterization always uses OpenAI Images (see openai_image_*).",
    )

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalize_llm_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_vision_model: str = "gpt-4o"
    openai_image_model: str = "dall-e-3"
    openai_image_size: str = "1024x1024"

    anthropic_api_key: str = ""
    anthropic_base_url: str | None = None
    anthropic_vision_model: str = "claude-sonnet-4-20250514"

    convertio_api_key: str = ""
    convertio_base_url: str = "https://api.convertio.co"
    convertio_poll_timeout_seconds: int = 300
    convertio_poll_interval_seconds: float = 2.0

    #: If set (e.g. `./debug_pipeline`), each successful LLM step writes `llm_styled_<id>.png` there.
    save_intermediate_png_dir: str | None = None


def get_settings() -> Settings:
    return Settings()


_settings: Settings | None = None


def get_settings_cached() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings
