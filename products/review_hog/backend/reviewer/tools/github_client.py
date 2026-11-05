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

from posthog.egress.github.transport import (
    GitHubEgressBudgetExhausted,
    GitHubRateLimitError,
    github_request,
    raise_if_github_rate_limited,
)
from posthog.egress.limiter.policies import Priority

from products.review_hog.backend.app_identity import posthog_app_login

logger = logging.getLogger(__name__)


def matches_app_bot(user: dict[str, Any] | None, app_login: str | None) -> bool:
    """Whether a GitHub review/comment author is OUR app's bot identity, given `posthog_app_login()`.

    Guards the marker-based idempotency scans: on a public repo anyone can paste a marker, and a
    spoofed match suppresses a publish or gets a stranger's comment PATCHed. `type == "Bot"` blocks
    human spoofers; when the `GITHUB_APP_SLUG` instance setting is set (the app's `<slug>[bot]` login),
    markers pasted by OTHER installed bots are rejected too. Unset, it fails closed in production,
    because any installed bot would pass. Local development and tests fall back to the type check:
    the app's own login isn't derivable from an installation token without extra API calls.

    Async callers resolve `app_login` once through `database_sync_to_async` and pass it in, because
    reading the instance setting can query the database, which Django refuses on an event loop.
    """
    author = user or {}
    if author.get("type") != "Bot":
        return False
    if app_login:
        return str(author.get("login") or "").lower() == app_login
    if settings.DEBUG or settings.TEST:
        return True
    logger.warning("GITHUB_APP_SLUG is not set; no GitHub author counts as the ReviewHog app")
    return False


def is_app_bot_author(user: dict[str, Any] | None) -> bool:
    """`matches_app_bot` against the configured app login, for sync callers only."""
    return matches_app_bot(user, posthog_app_login())


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


def is_transient_github_error(error: BaseException) -> bool:
    """A GitHub failure a later attempt can get past: our own budget, GitHub's rate limit, a 5xx, or the network."""
    return isinstance(error, GitHubEgressBudgetExhausted | GitHubRateLimitError | requests.RequestException) or (
        isinstance(error, GitHubAPIError) and error.status >= 500
    )


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


_REACTIONS_ENDPOINT = "/repos/{owner}/{repo}/issues/{issue_number}/reactions"


def add_pr_reaction(
    repository: str, pr_number: int, content: str, *, token: str, installation_id: str | None = None
) -> int | None:
    """React on the PR itself and return the reaction id, or None when GitHub refuses or fails.

    Fail-open: a reaction only tells people on the PR what the review is doing, so a failure is
    logged and never fails or retries the calling activity. GitHub returns the existing reaction
    when the app already reacted with `content`, so a retried activity gets the same id back.
    """
    try:
        response = github_api_request(
            "POST",
            f"/repos/{repository}/issues/{pr_number}/reactions",
            token=token,
            installation_id=installation_id,
            endpoint=_REACTIONS_ENDPOINT,
            json={"content": content},
        )
        reaction_id = response.json().get("id")
    except Exception:
        logger.warning("Could not add the %s reaction to %s#%s", content, repository, pr_number, exc_info=True)
        return None
    return reaction_id if isinstance(reaction_id, int) else None


def remove_pr_reaction(
    repository: str, pr_number: int, reaction_id: int, *, token: str, installation_id: str | None = None
) -> None:
    """Delete one reaction from the PR. A 404 means it is already gone.

    A transient error raises, so the calling activity retries it and no stale reaction stays on the
    PR. Any other error is logged and dropped, because a retry can not get past it.
    """
    try:
        github_api_request(
            "DELETE",
            f"/repos/{repository}/issues/{pr_number}/reactions/{reaction_id}",
            token=token,
            installation_id=installation_id,
            endpoint=f"{_REACTIONS_ENDPOINT}/{{reaction_id}}",
        )
    except Exception as e:
        if is_transient_github_error(e):
            raise
        if not (isinstance(e, GitHubAPIError) and e.status == 404):
            logger.warning("Could not remove reaction %s from %s#%s", reaction_id, repository, pr_number, exc_info=True)


def remove_own_pr_reactions(
    repository: str, pr_number: int, content: str, *, token: str, installation_id: str | None = None
) -> None:
    """Delete every `content` reaction the app left on the PR, and no one else's. Fail-open."""
    try:
        own_ids = [
            reaction["id"]
            for reaction in github_api_get_paginated(
                f"/repos/{repository}/issues/{pr_number}/reactions",
                token=token,
                installation_id=installation_id,
                endpoint=_REACTIONS_ENDPOINT,
                params={"content": content},
            )
            if is_app_bot_author(reaction.get("user"))
        ]
    except Exception:
        logger.warning("Could not read the %s reactions on %s#%s", content, repository, pr_number, exc_info=True)
        return
    for reaction_id in own_ids:
        try:
            remove_pr_reaction(repository, pr_number, reaction_id, token=token, installation_id=installation_id)
        except Exception:
            logger.warning("Could not remove reaction %s from %s#%s", reaction_id, repository, pr_number, exc_info=True)
