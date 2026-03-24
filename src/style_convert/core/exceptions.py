class StyleConvertError(Exception):
    """Base error for pipeline failures (mapped to HTTP errors in the app layer)."""


class LlmServiceError(StyleConvertError):
    """Vision / prompt synthesis or OpenAI image generation step failed."""


class LlmImageTooLargeError(LlmServiceError):
    """Input images exceed the vision provider’s per-image size limit (user can retry with smaller files)."""


class ConvertioServiceError(StyleConvertError):
    """Convertio API error (non-timeout)."""


class ConvertioTimeoutError(StyleConvertError):
    """Convertio polling exceeded configured timeout."""
