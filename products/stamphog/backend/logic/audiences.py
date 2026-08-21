"""Resolve a merged PR to the digest audiences it belongs to.

Ownership decides who hears about a merge:

- ``owned`` — one audience per team owning a file the PR changed, read back from the ownership
  the review already resolved against the checkout (see models.PullRequestAudience).
- ``repo_declared`` — one audience for a repo that declared its own digest channel (see
  logic/digest_config.py). It carries every one of that repo's merges to one place regardless of
  who owns what, which is what a standalone repo needs.

The author's own team is deliberately not an audience. A team hears about code it owns, not about
everywhere its members touched. A merge that no team owns, in a repo that declares nothing,
therefore reaches nobody: that is an ownership gap, and ``hogli owners:unowned`` is where it gets
fixed.

Digest grouping and channel routing key off the opaque audience string alone (see
models.DigestChannel).
"""

from __future__ import annotations

import re
from dataclasses import field
from typing import TYPE_CHECKING, Any

import structlog

from posthog.dataclasses import frozen

from ..facade.enums import AudienceReason
from .digest_config import load_repo_digest_config

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)

# The engine reports owning teams as GitHub handles; audience keys are bare slugs, matching what
# the author cascade produces and what channel resolution looks up.
_TEAM_HANDLE_PREFIX = "@"

# Ownership is resolved from owners.yaml in the PR-HEAD checkout — unlike .stamphog/*, those files
# are not replaced with default-branch copies, so an owner string is attacker-controlled. A slug is
# only ever a GitHub team name, so anything else is rejected rather than sanitized. This is what
# keeps a crafted owner out of the reserved "repo:" namespace, whose channel auto-enables and skips
# the shared-channel guard.
_TEAM_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@frozen
class _OwnerTeam:
    """One team's stake in a PR: its slug, a capped sample of its changed paths, and the true count."""

    slug: str
    files: list[str]
    file_count: int


@frozen
class ResolvedAudience:
    key: str
    reason: AudienceReason
    # Capped sample of this team's changed paths; empty unless reason is OWNED.
    owned_files: list[str] = field(default_factory=list)
    # How many files this team owns in the PR, uncapped.
    owned_file_count: int = 0


def _repository_audience_key(repo_config: StamphogRepoConfig) -> str:
    # The pending distributed owners.yaml resolver (PR #68872, contact.slack) is a channel-
    # resolution clue, not an audience_key source — it slots into logic/channel_resolution.py to
    # correct which Slack channel a "repo:" fallback lands in, not this cascade.
    return f"repo:{repo_config.repository}"


def _owner_teams(gate_result: dict[str, Any] | None) -> list[_OwnerTeam]:
    """Every team owning a changed file, with its path sample and true file count.

    The review walked the real checkout to get this, which the digest cannot do later. Anything
    unexpected in the blob resolves to "no owners" rather than raising: a merge must still be
    captured when the ownership section is missing or an older engine never wrote it.
    """
    ownership = ((gate_result or {}).get("classification") or {}).get("ownership") or {}
    teams = ownership.get("teams")
    if not isinstance(teams, list):
        return []
    files_by_team = ownership.get("team_files")
    if not isinstance(files_by_team, dict):
        files_by_team = {}
    counts_by_team = ownership.get("team_file_counts")
    if not isinstance(counts_by_team, dict):
        counts_by_team = {}
    owners = {}
    for team in teams:
        if not isinstance(team, str) or not team.startswith(_TEAM_HANDLE_PREFIX):
            continue
        # "@PostHog/team-devex" -> "team-devex". A handle without an org is not a team.
        _, _, slug = team.partition("/")
        if not _TEAM_SLUG_RE.match(slug):
            logger.warning("stamphog_owner_team_slug_rejected", team=team)
            continue
        paths = files_by_team.get(team)
        sample = [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
        count = counts_by_team.get(team)
        # Fall back to the sample size when the count is missing or nonsense; never below it.
        owners[slug] = (sample, max(count, len(sample)) if isinstance(count, int) else len(sample))
    return [_OwnerTeam(slug=slug, files=sample, file_count=count) for slug, (sample, count) in sorted(owners.items())]


def resolve_audiences(
    repo_config: StamphogRepoConfig,
    pr_payload: dict[str, Any],
    gate_result: dict[str, Any] | None = None,
) -> list[ResolvedAudience]:
    """Every audience a merged PR belongs to. Empty when nobody owns it and no repo claimed it.

    Membership is deliberately generous: a team owning a single changed file still gets an
    audience. Whether the PR is worth mentioning to that team is a later, per-digest judgment.

    A repo-declared audience sits alongside the owning teams rather than replacing them, so a
    shared repo still tells each team about its own area while a standalone repo gets the single
    feed it asked for.

    ``pr_payload`` is unused now that the author's team no longer forms an audience. It stays in
    the signature because both callers hold the payload, and a routing input read off the PR
    itself is a plausible near-term addition.
    """
    audiences = []
    digest_config = load_repo_digest_config(repo_config)
    if digest_config is not None and digest_config.channel:
        audiences.append(
            ResolvedAudience(key=_repository_audience_key(repo_config), reason=AudienceReason.REPO_DECLARED)
        )

    for owner in _owner_teams(gate_result):
        audiences.append(
            ResolvedAudience(
                key=owner.slug,
                reason=AudienceReason.OWNED,
                owned_files=owner.files,
                owned_file_count=owner.file_count,
            )
        )
    return audiences
