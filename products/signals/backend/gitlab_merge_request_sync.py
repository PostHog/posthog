"""Reads the state of unfinished GitLab merge requests that reports link.

GitHub tells PostHog about a merge or a close through a webhook. GitLab sends none, so a periodic sweep
reads each unfinished merge request and applies a change through the same path the webhook takes.
"""

import time

from django.db.models import F, Min
from django.utils import timezone

import requests
import structlog

from posthog.integrations import IntegrationRecord
from posthog.models.integration import GitLabIntegrationError

from products.signals.backend.gitlab_merge_requests import (
    GITLAB_REPOSITORY_PREFIX,
    MergeRequestRef,
    fetch_merge_request,
    gitlab_connection_for_merge_request,
    merge_request_ref_for_repository,
)
from products.signals.backend.models import SignalReportPullRequest
from products.signals.backend.report_assignments import update_assignments_for_pull_request

logger = structlog.get_logger(__name__)

MAX_MERGE_REQUESTS_PER_TEAM = 25
MAX_MERGE_REQUESTS_PER_SWEEP = 500

_UNFINISHED_STATES = (
    SignalReportPullRequest.State.UNKNOWN,
    SignalReportPullRequest.State.DRAFT,
    SignalReportPullRequest.State.OPEN,
)


def refresh_team_merge_requests(
    team_id: int, *, limit: int = MAX_MERGE_REQUESTS_PER_TEAM, deadline: float | None = None
) -> int:
    """Read the team's least recently checked unfinished merge requests. Returns how many changed state."""
    rows = list(
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(repository__startswith=GITLAB_REPOSITORY_PREFIX, state__in=_UNFINISHED_STATES)
        .order_by(F("checked_at").asc(nulls_first=True), "id")[:limit]
    )
    connections: dict[str, IntegrationRecord | None] = {}
    changed = 0
    for row in rows:
        if deadline is not None and time.monotonic() >= deadline:
            break
        ref = merge_request_ref_for_repository(row.repository, row.number)
        if ref is not None and ref.project_path not in connections:
            connections[ref.project_path] = gitlab_connection_for_merge_request(team_id, ref)
        integration = connections[ref.project_path] if ref is not None else None
        if ref is None or integration is None:
            # Without a connection the row cannot be read, and it must not hold the front of every sweep.
            _mark_checked(team_id, row)
            continue
        changed += _refresh_merge_request(team_id, row, ref, integration)
    return changed


def _mark_checked(team_id: int, row: SignalReportPullRequest) -> None:
    SignalReportPullRequest.objects.for_team(team_id).filter(id=row.id).update(checked_at=timezone.now())


def _refresh_merge_request(
    team_id: int, row: SignalReportPullRequest, ref: MergeRequestRef, integration: IntegrationRecord
) -> int:
    try:
        merge_request = fetch_merge_request(integration, ref)
    except (GitLabIntegrationError, requests.RequestException):
        logger.warning("signals.gitlab_merge_request_refresh_failed", team_id=team_id, pr_id=str(row.id))
        _mark_checked(team_id, row)
        return 0
    state = merge_request.state if merge_request is not None else row.state
    if state == row.state or state == SignalReportPullRequest.State.UNKNOWN:
        # Checked, so the next sweep starts with merge requests it has not read for longer.
        _mark_checked(team_id, row)
        return 0
    update_assignments_for_pull_request(
        team_ids=[team_id],
        repository=row.repository,
        pr_number=row.number,
        pr_state=state,
        merged_at=merge_request.merged_at if merge_request is not None else None,
    )
    return 1


def refresh_unfinished_merge_requests(*, deadline: float | None = None) -> int:
    """One sweep across teams, bounded per team and in total. Returns how many merge requests changed state."""
    # The teams whose merge requests waited longest go first, so a sweep that runs out of budget
    # does not starve the same teams every time.
    team_ids = list(
        SignalReportPullRequest.objects.unscoped()
        .filter(repository__startswith=GITLAB_REPOSITORY_PREFIX, state__in=_UNFINISHED_STATES)
        .values("team_id")
        .annotate(oldest_check=Min("checked_at"))
        .order_by(F("oldest_check").asc(nulls_first=True), "team_id")
        .values_list("team_id", flat=True)[:MAX_MERGE_REQUESTS_PER_SWEEP]
    )
    budget = MAX_MERGE_REQUESTS_PER_SWEEP
    changed = 0
    for team_id in team_ids:
        if budget <= 0 or (deadline is not None and time.monotonic() >= deadline):
            break
        limit = min(MAX_MERGE_REQUESTS_PER_TEAM, budget)
        budget -= limit
        try:
            changed += refresh_team_merge_requests(team_id, limit=limit, deadline=deadline)
        except Exception:
            logger.exception("signals.gitlab_merge_request_sweep_team_failed", team_id=team_id)
    return changed
