"""
GitHub API client wrapper for visual_review.

Centralizes auth headers, rate limit logging, and rate limit error detection
so individual call sites don't need to handle any of this.
"""

from __future__ import annotations

import requests
import structlog

from posthog.models.integration import GITHUB_API_VERSION, GitHubRateLimitError, raise_if_github_rate_limited

logger = structlog.get_logger(__name__)


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
    # raise_if_github_rate_limited handles detection and construction; we add structlog context here.
    try:
        raise_if_github_rate_limited(response)
    except GitHubRateLimitError as e:
        logger.error(  # noqa: TRY400 — rate limiting is expected; no traceback needed
            "visual_review.github_rate_limit_exceeded",
            method=method,
            url=_sanitize_url(url),
            status_code=response.status_code,
            reset_at=e.reset_at,
            retry_after=e.retry_after,
            remaining=response.headers.get("x-ratelimit-remaining"),
            limit=response.headers.get("x-ratelimit-limit"),
            resource=response.headers.get("x-ratelimit-resource"),
        )
        raise


def _sanitize_url(url: str) -> str:
    """Strip query params from URL for logging (may contain tokens in rare cases)."""
    return url.split("?")[0]
