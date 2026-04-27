"""
GitHub API client wrapper for visual_review.

Centralizes auth headers, rate limit logging, and rate limit error detection
so individual call sites don't need to handle any of this.
"""

from __future__ import annotations

import time

import requests
import structlog

logger = structlog.get_logger(__name__)

GITHUB_API_VERSION = "2022-11-28"


class GitHubRateLimitError(Exception):
    """GitHub API rate limit exhausted for this installation."""

    def __init__(self, message: str, reset_at: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.reset_at = reset_at
        self.retry_after = retry_after


def github_request(
    method: str,
    url: str,
    access_token: str,
    **kwargs,
) -> requests.Response:
    """Make a GitHub API request with standard headers, rate limit logging, and rate limit detection.

    Raises GitHubRateLimitError on 403/429 when the rate limit is exhausted.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        **(kwargs.pop("headers", {})),
    }

    response = requests.request(method, url, headers=headers, **kwargs)

    _log_rate_limit_headers(response, method, url)
    _check_rate_limit_response(response, method, url)

    return response


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _log_rate_limit_headers(response: requests.Response, method: str, url: str) -> None:
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining is None:
        return

    limit = response.headers.get("x-ratelimit-limit")
    used = response.headers.get("x-ratelimit-used")
    reset = response.headers.get("x-ratelimit-reset")
    resource = response.headers.get("x-ratelimit-resource")

    remaining_int = _safe_int(remaining)

    if remaining_int is not None and remaining_int < 100:
        logger.warning(
            "visual_review.github_rate_limit_low",
            remaining=remaining,
            limit=limit,
            used=used,
            reset=reset,
            resource=resource,
            method=method,
            url=_sanitize_url(url),
        )
    else:
        logger.debug(
            "visual_review.github_rate_limit",
            remaining=remaining,
            limit=limit,
            used=used,
            resource=resource,
        )


def _check_rate_limit_response(response: requests.Response, method: str, url: str) -> None:
    # GitHub returns 429 for secondary rate limits (concurrent request limits)
    # and 403 with "rate limit" in the body for primary rate limits.
    if response.status_code == 429:
        is_rate_limited = True
    elif response.status_code == 403:
        body = ""
        try:
            body = response.text
        except Exception:
            pass
        is_rate_limited = "rate limit" in body.lower()
    else:
        return

    if not is_rate_limited:
        return

    reset_at = _safe_int(response.headers.get("x-ratelimit-reset"))
    retry_after_seconds = _safe_int(response.headers.get("retry-after"))

    # Derive retry_after from reset_at when GitHub only sends the reset timestamp
    if retry_after_seconds is None and reset_at is not None:
        retry_after_seconds = max(1, reset_at - int(time.time()))

    logger.error(
        "visual_review.github_rate_limit_exceeded",
        method=method,
        url=_sanitize_url(url),
        status_code=response.status_code,
        reset_at=reset_at,
        retry_after=retry_after_seconds,
        remaining=response.headers.get("x-ratelimit-remaining"),
        limit=response.headers.get("x-ratelimit-limit"),
        resource=response.headers.get("x-ratelimit-resource"),
    )

    raise GitHubRateLimitError(
        f"GitHub API rate limit exceeded (resets at {reset_at})",
        reset_at=reset_at,
        retry_after=retry_after_seconds,
    )


def _sanitize_url(url: str) -> str:
    """Strip query params from URL for logging (may contain tokens in rare cases)."""
    return url.split("?")[0]
