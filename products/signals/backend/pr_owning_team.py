"""DRI candidates from the GitHub team that owns the files a pull request changes.

A repository that declares its ownership in `owners.yaml` files names a GitHub team for each path.
That team answers for the code today, which commit history does not tell. A repository without
those files gets no candidates here, and the caller uses the suggested reviewers instead.
"""

from __future__ import annotations

import re
import random
from collections import Counter

import structlog

from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)

# The slug comes from the repository's own files and goes into a GitHub API path, so anything that
# is not a plain GitHub team slug is refused.
_TEAM_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class OwningTeamCandidates:
    """The members of the team that owns most of a pull request's files, as DRI candidates."""

    def __init__(self, github: GitHubIntegration, *, team_id: int, report_id: str, parsed: PullRequestRef) -> None:
        self.github = github
        self.team_id = team_id
        self.parsed = parsed
        self.log = logger.bind(
            team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number
        )

    def _owning_team(self) -> str | None:
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
        team_slug = counts.most_common(1)[0][0]
        if not _TEAM_SLUG_RE.match(team_slug):
            self.log.warning("signals.pr_owning_team.invalid_team_slug")
            return None
        return team_slug

    def logins(self) -> list[str]:
        """Team members who are organization members with a connected GitHub account, in random order.

        Empty when the repository declares no ownership, no team owns the files, or GitHub does not
        list the team. A missing organization members permission on the GitHub app is that last case.
        """
        team_slug = self._owning_team()
        if team_slug is None:
            return []

        members = self.github.list_team_members(self.parsed.owner, team_slug)
        if not members.get("success"):
            self.log.warning(
                "signals.pr_owning_team.members_fetch_failed",
                team_slug=team_slug,
                status_code=members.get("status_code"),
            )
            return []

        logins = list(resolve_org_github_login_to_users(self.team_id, members["logins"]))
        # TODO: prefer the member with the fewest open self-driving pull requests, to spread the load.
        random.shuffle(logins)
        self.log.info("signals.pr_owning_team.resolved", team_slug=team_slug, candidates=len(logins))
        return logins
