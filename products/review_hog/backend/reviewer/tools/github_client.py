"""ReviewHog's thin GitHub REST layer over the gated egress transport.

Every ReviewHog call to GitHub goes through `github_api_request` / `github_api_get_paginated`, which
route through `posthog.egress.github.transport.github_request` — budget-gated per installation and
recorded on the egress telemetry by construction. Auth is the caller-held App installation token;
pass `installation_id` alongside it so the call is metered against that installation's shared budget.
"""

import logging
from collections.abc import Iterator
from typing import Any

from django.conf import settings

import requests

from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority

logger = logging.getLogger(__name__)


def is_app_bot_author(user: dict[str, Any] | None) -> bool:
    """Whether a GitHub review/comment author is OUR app's bot identity.

    Guards the marker-based idempotency scans: on a public repo anyone can paste a marker, and a
    spoofed match suppresses a publish or gets a stranger's comment PATCHed. `type == "Bot"` blocks
    human spoofers; when `REVIEWHOG_GITHUB_BOT_LOGIN` is configured (the app's `<slug>[bot]` login),
    markers pasted by OTHER installed bots are rejected too. Unset fails open to the type check —
    the app's own login isn't derivable from an installation token without extra API calls.
    """
    author = user or {}
    if author.get("type") != "Bot":
        return False
    expected = settings.REVIEWHOG_GITHUB_BOT_LOGIN
    return author.get("login") == expected if expected else True


GITHUB_API_BASE = "https://api.github.com"

_SOURCE = "review_hog"
_PER_PAGE = 100
_TIMEOUT = 30.0


class GitHubAPIError(Exception):
    """A GitHub REST call returned a non-2xx status (rate limits raise `GitHubRateLimitError` instead)."""

    def __init__(self, message: str, *, status: int, api_message: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.api_message = api_message


def _api_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return response.text[:200]


def github_api_request(
    method: str,
    path: str,
    *,
    token: str,
    endpoint: str,
    installation_id: str | None = None,
    params: dict[str, str | int] | None = None,
    json: dict[str, Any] | None = None,
) -> requests.Response:
    """One gated, recorded GitHub REST call. `path` is the API path (`/repos/...`); `endpoint` is its
    normalized template (`/repos/{owner}/{repo}/...`) for bounded-cardinality telemetry labels.

    Raises `GitHubRateLimitError` when GitHub rate-limits the call and `GitHubAPIError` on any other
    non-2xx status; transport-level failures propagate as `requests` exceptions.
    """
    response = github_request(
        method,
        f"{GITHUB_API_BASE}{path}",
        source=_SOURCE,
        headers={"Authorization": f"Bearer {token}"},
        installation_id=installation_id,
        # NORMAL, not the transport's CRITICAL default: a review is automated (nobody blocks on any
        # single call, and Temporal retries a shed one), so it must not burn the reserve kept for
        # genuinely interactive traffic on the shared installation budget. Not BATCH either — devs
        # do wait on the review after a push, so it shouldn't be first in line for shedding.
        priority=Priority.NORMAL,
        endpoint=endpoint,
        params=params,
        json=json,
        timeout=_TIMEOUT,
    )
    raise_if_github_rate_limited(response)
    if not response.ok:
        api_message = _api_message(response)
        raise GitHubAPIError(
            f"GitHub API {method} {endpoint} returned {response.status_code}: {api_message}",
            status=response.status_code,
            api_message=api_message,
        )
    return response


def github_api_get_paginated(
    path: str,
    *,
    token: str,
    endpoint: str,
    installation_id: str | None = None,
    params: dict[str, str | int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every item of a paginated list endpoint, fetching `per_page=100` pages until a short page."""
    page = 1
    while True:
        response = github_api_request(
            "GET",
            path,
            token=token,
            endpoint=endpoint,
            installation_id=installation_id,
            params={**(params or {}), "per_page": _PER_PAGE, "page": page},
        )
        items = response.json()
        yield from items
        if len(items) < _PER_PAGE:
            return
        page += 1
