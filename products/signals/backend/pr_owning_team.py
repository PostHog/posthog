"""The GitHub team that owns the files a pull request changes, and its members as DRI candidates.

A repository that declares its ownership in `owners.yaml` files names a GitHub team for each path.
That team answers for the code today, which commit history does not tell. A repository without
those files gets no team here, and the caller uses the suggested reviewers instead.
"""

from __future__ import annotations

import re
import random
from collections import Counter

import structlog

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM

logger = structlog.get_logger(__name__)

# The slug comes from the repository's own files and goes into a GitHub API path, so anything that
# is not a plain GitHub team slug is refused.
_TEAM_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@frozen
class OwningTeam:
    slug: str
    # Lowercase GitHub logins of every team member, in random order. GitHub team membership is the
    # ownership, so a member needs no PostHog account.
    logins: tuple[str, ...]


class OwningTeamResolver:
    """Finds the team that owns most of a pull request's files, and its members."""

    def __init__(self, github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef) -> None:
        self.github = github
        self.parsed = parsed
        self.log = logger.bind(
            team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number
        )

    def _team_slug(self) -> str | None:
        files = self.github.list_pull_request_files(self.parsed.repository, self.parsed.number)
        if not files.get("success"):
            self.log.warning("signals.pr_owning_team.files_fetch_failed", error=files.get("error"))
            return None
        if not files["paths"]:
            return None

        ownership = resolve_path_owners(self.parsed.repository, files["paths"])
        if not ownership.resolved:
            return None
        counts = Counter(team for team in ownership.team_by_path.values() if team != UNOWNED_TEAM)
        if not counts:
            return None
        slug = counts.most_common(1)[0][0]
        if not _TEAM_SLUG_RE.match(slug):
            self.log.warning("signals.pr_owning_team.invalid_team_slug")
            return None
        return slug

    def resolve(self) -> OwningTeam | None:
        """The owning team, or None when the repository declares no ownership, no team owns the files,
        or GitHub does not list the team. A missing organization members permission on the GitHub app
        is that last case.
        """
        slug = self._team_slug()
        if slug is None:
            return None

        members = self.github.list_team_members(self.parsed.owner, slug)
        if not members.get("success"):
            self.log.warning(
                "signals.pr_owning_team.members_fetch_failed", team_slug=slug, status_code=members.get("status_code")
            )
            return None

        # Lowercase, so the logins match the normalized suggested reviewer and opt-in logins.
        logins = list(dict.fromkeys(login.lower() for login in members["logins"]))
        # TODO: prefer the member with the fewest open self-driving pull requests, to spread the load.
        random.shuffle(logins)
        self.log.info("signals.pr_owning_team.resolved", team_slug=slug, candidates=len(logins))
        return OwningTeam(slug=slug, logins=tuple(logins))
