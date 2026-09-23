"""Gemini API key resolution and error classification for Replay Vision."""

import sys

from django.conf import settings

import httpx
import aiohttp
from google.genai import types
from google.genai.errors import APIError, UnknownApiResponseError

from products.replay_vision.backend.error_kinds import FailureKind

# CPython refuses to build an int from a string longer than 4,300 digits, and the SDK parses every provider
# response with `json.loads`, so a model that emits a runaway digit run kills the scan before we see the body.
# A response is bounded by the model's output-token cap, so this ceiling is far above any answer the provider
# can return, and a conversion at this length still costs about ten milliseconds.
_MAX_JSON_INT_DIGITS = 100_000


def gemini_api_key() -> str:
    """Replay Vision's dedicated key (own GCP project), falling back to the shared key where unset."""
    return settings.REPLAY_VISION_GEMINI_API_KEY or settings.GEMINI_API_KEY


def raise_json_int_digit_limit() -> None:
    """Let the scanner worker parse a provider response that holds a very long number."""
    if sys.get_int_max_str_digits() < _MAX_JSON_INT_DIGITS:
        sys.set_int_max_str_digits(_MAX_JSON_INT_DIGITS)


# 408 request timeout and 409 conflict join the usual rate-limit/5xx set: all clear on their own.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})

# Connection-level failures raised before any HTTP response exists (DNS, TLS, resets, read timeouts). The
# google-genai SDK uses aiohttp when installed and httpx otherwise, and lets both stacks' transport errors
# propagate raw; an unreachable provider is the same user story as a 5xx. Anything outside these two
# hierarchies stays unclassified on purpose, because it can come from our own code.
_PROVIDER_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    aiohttp.ClientConnectionError,
)


def describe_gemini_error(error: BaseException) -> str:
    """Fixed-shape summary for user-visible error reasons.

    The raw error can quote parts of the request (prompt text, file references), so it must never reach
    `error_reason`; callers log the full error and show the user only the shape of the failure.
    """
    if isinstance(error, APIError):
        status = f" {error.status}" if error.status else ""
        return f"The AI provider returned HTTP {error.code}{status}"
    if _is_unreadable_response(error):
        return "The AI provider returned a response PostHog could not read"
    return f"PostHog could not reach the AI provider ({type(error).__name__})"


def _is_unreadable_response(error: BaseException) -> bool:
    """Whether the provider sent a body the SDK could not turn into JSON.

    The next draw usually parses, so this is transient: it must not reach the user as `internal_error`, and the
    cached-run fallback must not re-spend the video tokens on it. The SDK raises `UnknownApiResponseError` for a
    malformed body, but a number longer than the interpreter's digit limit escapes as a bare `ValueError` from
    `int()`, which only its message identifies.
    """
    if isinstance(error, UnknownApiResponseError):
        return True
    return type(error) is ValueError and "integer string conversion" in str(error)


def classify_gemini_error(error: BaseException) -> FailureKind | None:
    """Map a `google-genai` provider error onto a failure kind, or None when it isn't one.

    Without this every provider hiccup (a 429 during a quota window, a 503 mid-outage, a dropped connection)
    reaches the workflow as an unrecognized exception and lands as `internal_error`, which tells the user to
    contact support about an outage they can just retry. Errors we can't place stay None so they keep the
    unclassified path rather than claiming to be transient and burning the retry budget.
    """
    if isinstance(error, _PROVIDER_TRANSPORT_ERRORS):
        return FailureKind.PROVIDER_TRANSIENT
    if _is_unreadable_response(error):
        return FailureKind.PROVIDER_TRANSIENT
    if not isinstance(error, APIError):
        return None
    if error.code in _TRANSIENT_STATUS_CODES:
        return FailureKind.PROVIDER_TRANSIENT
    # A 4xx we didn't list is the provider refusing this input (unsupported video, too large, safety block).
    if isinstance(error.code, int) and 400 <= error.code < 500:
        return FailureKind.PROVIDER_REJECTED
    return None


# `File.error` carries a `google.rpc.Status`, so its code is a canonical gRPC code rather than an HTTP status.
# Only the codes that mean the provider refused this input are terminal.
_REJECTING_FILE_ERROR_CODES = frozenset(
    {
        3,  # INVALID_ARGUMENT
        5,  # NOT_FOUND
        7,  # PERMISSION_DENIED
        9,  # FAILED_PRECONDITION
        11,  # OUT_OF_RANGE
        12,  # UNIMPLEMENTED
        16,  # UNAUTHENTICATED
    }
)


def classify_gemini_file_error(error: types.FileStatus | None) -> FailureKind:
    """Map the provider's own per-file error onto a failure kind for a file that never became ACTIVE.

    A failure inside the provider's own video processing usually clears on a re-upload, so anything the codes
    don't place as a refused input stays transient and gets the activity's retry budget. A kind that claims the
    provider won't recover is terminal, and tells the user a retry reaches the same answer.
    """
    code = error.code if error else None
    if code in _REJECTING_FILE_ERROR_CODES:
        return FailureKind.PROVIDER_REJECTED
    return FailureKind.PROVIDER_TRANSIENT


def describe_gemini_file_error(error: types.FileStatus | None) -> str:
    """Fixed-shape summary for user-visible error reasons; the provider's message can quote request content."""
    if error and error.code is not None:
        return f"The AI provider could not process the video (error code {error.code})"
    return "The AI provider could not process the video"
