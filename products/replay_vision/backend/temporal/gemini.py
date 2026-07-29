"""Gemini API key resolution and error classification for Replay Vision."""

from django.conf import settings

from google.genai.errors import APIError

from products.replay_vision.backend.error_kinds import FailureKind


def gemini_api_key() -> str:
    """Replay Vision's dedicated key (own GCP project), falling back to the shared key where unset."""
    return settings.REPLAY_VISION_GEMINI_API_KEY or settings.GEMINI_API_KEY


# 408 request timeout and 409 conflict join the usual rate-limit/5xx set: all clear on their own.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


def classify_gemini_error(error: BaseException) -> FailureKind | None:
    """Map a `google-genai` transport error onto a failure kind, or None when it isn't one.

    Without this every provider hiccup (a 429 during a quota window, a 503 mid-outage) reaches the workflow as an
    unrecognized exception and lands as `internal_error`, which tells the user to contact support about an outage
    they can just retry. Codes we can't place stay None so they keep the unclassified path rather than claiming to
    be transient and burning the retry budget.
    """
    if not isinstance(error, APIError):
        return None
    if error.code in _TRANSIENT_STATUS_CODES:
        return FailureKind.PROVIDER_TRANSIENT
    # A 4xx we didn't list is the provider refusing this input (unsupported video, too large, safety block).
    if isinstance(error.code, int) and 400 <= error.code < 500:
        return FailureKind.PROVIDER_REJECTED
    return None
