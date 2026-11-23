"""Merge requests that Self-driving opens on gitlab.com projects, tracked like GitHub pull requests.

A merge request is stored as a `SignalReportPullRequest` whose repository is `gitlab.com/<project path>`
and whose number is the merge request iid. The host prefix keeps it apart from a GitHub repository with
the same path, and GitHub code that receives the identity finds no installation for it.
"""

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationRecord
from posthog.models.github_integration_base import GitHubIntegrationBase, PullRequestRef
from posthog.models.integration import GitLabIntegration

from products.signals.backend.models import SignalReportAssignment
from products.signals.backend.self_driving_gitlab import self_driving_gitlab_enabled
from products.tasks.backend.facade.repo_selection import gitlab_project_for_repository

logger = structlog.get_logger(__name__)

GITLAB_REPOSITORY_PREFIX = "gitlab.com/"
_GITLAB_HOSTS = frozenset({"gitlab.com", "www.gitlab.com"})


@frozen
class MergeRequestRef:
    project_path: str
    number: int

    @property
    def repository(self) -> str:
        return f"{GITLAB_REPOSITORY_PREFIX}{self.project_path}"


def parse_merge_request_url(url: str) -> MergeRequestRef | None:
    """Parse `https://gitlab.com/<namespace>/<project>/-/merge_requests/<iid>[/...]`, or None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() not in _GITLAB_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if "-" not in parts:
        return None
    marker = parts.index("-")
    project_parts = parts[:marker]
    if len(project_parts) < 2 or len(parts) < marker + 3 or parts[marker + 1] != "merge_requests":
        return None
    number = parts[marker + 2]
    if not (number.isascii() and number.isdigit()):
        return None
    return MergeRequestRef(project_path="/".join(project_parts), number=int(number))


def parse_implementation_pr_url(url: str) -> PullRequestRef | MergeRequestRef | None:
    """A GitHub pull request or a gitlab.com merge request. Both expose `repository` and `number`."""
    return GitHubIntegrationBase.parse_pull_request_url(url) or parse_merge_request_url(url)


def is_implementation_pr_url(url: object) -> bool:
    return isinstance(url, str) and parse_implementation_pr_url(url) is not None


def merge_request_ref_for_repository(repository: str, number: int) -> MergeRequestRef | None:
    """The merge request behind a stored `(repository, number)` identity, or None for a GitHub one."""
    if not repository.lower().startswith(GITLAB_REPOSITORY_PREFIX):
        return None
    return MergeRequestRef(project_path=repository[len(GITLAB_REPOSITORY_PREFIX) :], number=number)


@frozen
class MergeRequestStatus:
    web_url: str | None
    state: str
    merged_at: datetime | None
    reviewer_ids: tuple[int, ...]


def pr_state_for_merge_request(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if state == "merged":
        return SignalReportAssignment.PrState.MERGED
    if state == "closed":
        return SignalReportAssignment.PrState.CLOSED
    if state == "opened":
        return SignalReportAssignment.PrState.DRAFT if payload.get("draft") else SignalReportAssignment.PrState.OPEN
    # GitLab reports "locked" only while a merge is in progress, so the next read settles it.
    return SignalReportAssignment.PrState.UNKNOWN


def merge_request_status(payload: dict[str, Any]) -> MergeRequestStatus:
    state = pr_state_for_merge_request(payload)
    raw_merged_at = payload.get("merged_at")
    merged_at = parse_datetime(raw_merged_at) if isinstance(raw_merged_at, str) else None
    return MergeRequestStatus(
        web_url=payload.get("web_url") if isinstance(payload.get("web_url"), str) else None,
        state=state,
        merged_at=merged_at
        if state == SignalReportAssignment.PrState.MERGED and merged_at is not None and timezone.is_aware(merged_at)
        else None,
        reviewer_ids=tuple(
            int(reviewer["id"])
            for reviewer in payload.get("reviewers") or []
            if isinstance(reviewer, dict) and isinstance(reviewer.get("id"), int)
        ),
    )


def gitlab_connection_for_merge_request(team_id: int, ref: MergeRequestRef) -> IntegrationRecord | None:
    """The team's gitlab.com connection for the merge request's project, or None while the flag is off."""
    if not self_driving_gitlab_enabled(team_id):
        return None
    return gitlab_project_for_repository(team_id, ref.project_path)


def fetch_merge_request(integration: IntegrationRecord, ref: MergeRequestRef) -> MergeRequestStatus | None:
    """The merge request as GitLab reports it, or None when GitLab cannot find it. Raises on a failed read."""
    payload = GitLabIntegration(integration).get_merge_request_details(
        int(integration.config["project_id"]), ref.number
    )
    return merge_request_status(payload) if payload is not None else None
