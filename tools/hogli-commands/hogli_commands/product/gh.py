"""GitHub API helpers with caching."""

from __future__ import annotations

from posthog_owners.github import GitHubLookupError, GitHubOrg

_ORG = GitHubOrg("PostHog")


def get_team_slugs() -> tuple[set[str] | None, str]:
    """Fetch GitHub team slugs visible in the PostHog org. Cached after the first call.

    The org lookup is broader than repo access. assign-reviewers.js covers a team that exists
    in the org but lacks repo access with its 422 fallback, which retries each team individually
    and logs the bad slugs.

    Returns ``(slugs, error_message)``. ``slugs`` is ``None`` when the fetch failed.
    """
    try:
        return _ORG.team_slugs(), ""
    except GitHubLookupError as exc:
        return None, str(exc)
