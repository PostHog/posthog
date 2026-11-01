"""Parses the repo-declared `digest:` section of `.stamphog/policy.yml` — the single Slack
channel for ALL of a repo's merged-PR digests, if the repo owner wants to opt out of the
audience cascade.

Read from the target repo's DEFAULT branch only (never the PR head), same master-read
security model as the sandboxed review engine's policy pipeline (products/stamphog/packages/pr-approval-agent/
policy.py) — a PR must not be able to redirect its own digest.
Only the top-level `digest` key is read here; the rest of the policy schema is that
engine's concern and is neither parsed nor validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from .default_branch_policy import load_default_branch_policy

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RepoDigestConfig:
    channel: str | None


def _parse_channel(digest_raw: object, repository: str) -> str | None:
    if not isinstance(digest_raw, dict):
        logger.warning("stamphog_digest_config_not_a_mapping", repository=repository)
        return None
    channel = digest_raw.get("channel")
    if not isinstance(channel, str) or not channel.strip():
        logger.warning("stamphog_digest_config_missing_channel", repository=repository)
        return None
    return channel.strip().lstrip("#").strip()


def load_repo_digest_config(repo_config: StamphogRepoConfig) -> RepoDigestConfig | None:
    """Fetch `.stamphog/policy.yml` from the repo's default branch and read its `digest:` section.

    None means CONFIRMED absence or an unusable config: a missing file, no `digest` key, malformed
    YAML, or a bad `channel` value (warning logged so a repo owner's typo doesn't silently vanish).
    A transient fetch failure raises instead — the caller persists the resolved audience on the
    merged PR and never recomputes it, so swallowing a GitHub blip here would permanently route the
    merge to the author/team fallback instead of the declared channel. The merge-record Celery task
    retries on the raised error.
    """
    parsed = load_default_branch_policy(repo_config)
    if parsed is None or "digest" not in parsed:
        return None

    channel = _parse_channel(parsed["digest"], repo_config.repository)
    return RepoDigestConfig(channel=channel)
