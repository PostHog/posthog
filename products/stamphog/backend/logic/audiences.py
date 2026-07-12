"""Resolve a merged PR to a digest ``audience_key``.

One global best-effort cascade, no per-repo configuration: PR author -> GitHub team slug ->
"repo:{repository}" fallback. Digest grouping and channel routing key off that opaque string
alone (see models.DigestChannel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from .github_client import StamphogGitHubClient

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)


def _repository_audience_key(repo_config: StamphogRepoConfig) -> str:
    # The pending distributed owners.yaml resolver (PR #68872, contact.slack) is a channel-
    # resolution clue, not an audience_key source — it slots into logic/channel_resolution.py to
    # correct which Slack channel a "repo:" fallback lands in, not this cascade.
    return f"repo:{repo_config.repository}"


def _author_team_audience_key(repo_config: StamphogRepoConfig, pr_payload: dict[str, Any]) -> str:
    """Resolve the PR author's GitHub team, live, via the org's team memberships.

    Falls back to the repository key (with a warning) whenever the author has no resolvable team —
    missing fields, no team membership, or a failed lookup. Wrapped end-to-end so a flaky GitHub call
    never blocks capture of the merged PR itself.
    """
    try:
        login = ((pr_payload or {}).get("user") or {}).get("login")
        org = (repo_config.repository or "").split("/", 1)[0]
        if not login or not org:
            logger.warning(
                "stamphog_author_team_audience_missing_fields",
                repository=repo_config.repository,
                has_login=bool(login),
            )
            return _repository_audience_key(repo_config)

        # One GraphQL call per merged PR — merge volume is tiny next to API limits, not worth a cache.
        slugs = StamphogGitHubClient(repo_config.installation_id).get_user_team_slugs(org, login)
        if not slugs:
            logger.warning("stamphog_author_team_audience_no_team", repository=repo_config.repository, login=login)
            return _repository_audience_key(repo_config)

        chosen, *other_teams = slugs
        if other_teams:
            logger.info(
                "stamphog_author_team_audience_multiple_teams",
                login=login,
                chosen=chosen,
                other_teams=other_teams,
            )
        return chosen
    except Exception:
        logger.warning(
            "stamphog_author_team_audience_resolution_failed", repository=repo_config.repository, exc_info=True
        )
        return _repository_audience_key(repo_config)


def resolve_audience_key(repo_config: StamphogRepoConfig, pr_payload: dict[str, Any]) -> str:
    """Map a merged PR to its digest audience_key via the single global cascade."""
    return _author_team_audience_key(repo_config, pr_payload)
