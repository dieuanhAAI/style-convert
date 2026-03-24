from pydantic import BaseModel, Field


class ConvertFormFields(BaseModel):
    """Validates the text field for multipart `/convert` (files validated separately in the router)."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="Instructions for the style transfer.",
    )


class ConvertDownloadMetadata(BaseModel):
    """Describes the downloadable `.ai` response (for docs / logging; response body is raw bytes)."""

    filename: str = Field(..., description='e.g. "output_<uuid>.ai".')
