"""Claim and pull request lifecycle for signal reports."""

from __future__ import annotations

from typing import TypedDict

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration
from posthog.models.user import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import InvalidStatusTransition, SignalReport, SignalReportAssignment

logger = structlog.get_logger(__name__)

# The parser accepts any integer and any owner/repo length, but the columns are a positive bigint
# and a bounded varchar — so a hand-crafted URL only fails once the row reaches Postgres.
MAX_PR_NUMBER = 2**63 - 1
MAX_REPOSITORY_LENGTH = SignalReportAssignment._meta.get_field("repository").max_length or 200

CLAIMABLE_REPORT_STATUSES = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.SUPPRESSED,
    }
)


class ReportClaimConflict(Exception):
    pass


class InvalidPullRequestUrl(Exception):
    pass


class AssigneeSnapshot(TypedDict):
    kind: str
    user_id: int | None
    task_id: str | None
    agent: str | None
    claimed_at: str | None


class PullRequestSnapshot(TypedDict):
    url: str
    repository: str | None
    number: int | None
    state: str | None
    merged: bool


class AssignmentSnapshot(TypedDict):
    assignee: AssigneeSnapshot | None
    implementation_pr: PullRequestSnapshot | None


@frozen
class PullRequestDetails:
    url: str
    repository: str
    number: int
    state: str
    merged: bool


def assignment_snapshot(assignment: SignalReportAssignment | None) -> AssignmentSnapshot:
    if assignment is None:
        return {"assignee": None, "implementation_pr": None}
    assignee: AssigneeSnapshot | None = None
    if assignment.actor_kind:
        assignee = {
            "kind": assignment.actor_kind,
            "user_id": assignment.actor_user_id,
            "task_id": str(assignment.actor_task_id) if assignment.actor_task_id else None,
            "agent": assignment.actor_agent,
            "claimed_at": assignment.claimed_at.isoformat() if assignment.claimed_at else None,
        }
    implementation_pr: PullRequestSnapshot | None = None
    if assignment.pr_url:
        implementation_pr = {
            "url": assignment.pr_url,
            "repository": assignment.repository,
            "number": assignment.pr_number,
            "state": assignment.pr_state,
            "merged": assignment.pr_merged,
        }
    return {"assignee": assignee, "implementation_pr": implementation_pr}


def actor_owns_assignment(assignment: SignalReportAssignment, actor: ArtefactAttribution) -> bool:
    if assignment.actor_kind != actor.kind:
        return False
    if actor.kind == "user":
        return assignment.actor_user_id == actor.user_id
    if actor.kind == "task":
        return str(assignment.actor_task_id) == actor.task_id
    if actor.kind == "agent":
        return assignment.actor_user_id == actor.user_id and assignment.actor_agent == actor.agent_name
    return actor.kind == "system"


def _set_actor(assignment: SignalReportAssignment, actor: ArtefactAttribution) -> None:
    assignment.actor_kind = actor.kind
    assignment.actor_user_id = actor.user_id
    assignment.actor_task_id = actor.task_id
    assignment.actor_agent = actor.agent_name
    assignment.claimed_at = timezone.now()


def _clear_actor(assignment: SignalReportAssignment) -> None:
    assignment.actor_kind = None
    assignment.actor_user_id = None
    assignment.actor_task_id = None
    assignment.actor_agent = None
    assignment.claimed_at = None


def _pull_request_details(team_id: int, pr_url: str) -> PullRequestDetails:
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        raise InvalidPullRequestUrl("pr_url must be a GitHub pull request URL.")
    if not 0 < parsed.number <= MAX_PR_NUMBER:
        raise InvalidPullRequestUrl("pr_url must end in a positive pull request number.")
    repository = parsed.repository.lower()
    if len(repository) > MAX_REPOSITORY_LENGTH:
        raise InvalidPullRequestUrl("pr_url repository name is too long.")

    details = PullRequestDetails(
        url=pr_url,
        repository=repository,
        number=parsed.number,
        state=SignalReportAssignment.PrState.UNKNOWN,
        merged=False,
    )
    try:
        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    except Exception:
        logger.exception(
            "signals.assignment.integration_lookup_failed",
            team_id=team_id,
            repository=parsed.repository,
        )
        return details
    if github is None:
        return details

    try:
        status = github.get_pull_request(parsed.repository, parsed.number)
    except Exception:
        logger.exception(
            "signals.assignment.pr_fetch_failed",
            team_id=team_id,
            repository=parsed.repository,
            pr_number=parsed.number,
        )
        return details
    if not status.get("success"):
        logger.warning(
            "signals.assignment.pr_fetch_failed",
            team_id=team_id,
            repository=parsed.repository,
            pr_number=parsed.number,
            error=status.get("error"),
        )
        return details

    merged = bool(status.get("merged"))
    if merged:
        pr_state = SignalReportAssignment.PrState.MERGED
    elif status.get("state") == "closed":
        pr_state = SignalReportAssignment.PrState.CLOSED
    elif status.get("draft"):
        pr_state = SignalReportAssignment.PrState.DRAFT
    elif status.get("state") == "open":
        pr_state = SignalReportAssignment.PrState.OPEN
    else:
        pr_state = SignalReportAssignment.PrState.UNKNOWN
    return PullRequestDetails(
        url=status.get("url") or pr_url,
        repository=details.repository,
        number=details.number,
        state=pr_state,
        merged=merged,
    )


def _apply_pr_report_state(report: SignalReport, pr_state: str | None) -> None:
    target = None
    if pr_state == SignalReportAssignment.PrState.MERGED:
        target = SignalReport.Status.RESOLVED
    elif pr_state == SignalReportAssignment.PrState.CLOSED:
        target = SignalReport.Status.SUPPRESSED
    if target is None or report.status == target:
        return
    try:
        updated_fields = report.transition_to(target)
    except (InvalidStatusTransition, ValueError, TypeError):
        logger.info(
            "signals.assignment.pr_state_transition_skipped",
            report_id=str(report.id),
            report_status=report.status,
            pr_state=pr_state,
        )
        return
    report.save(update_fields=updated_fields)


def claim_report(
    *,
    report: SignalReport,
    actor: ArtefactAttribution,
    user: User,
    was_impersonated: bool,
    pr_url: str | None,
    release: bool,
) -> SignalReportAssignment | None:
    """Claim, release, or attach a PR to one report and return the current assignment."""
    if not release and report.status not in CLAIMABLE_REPORT_STATUSES:
        raise ReportClaimConflict(f"Reports with status '{report.status}' cannot be claimed.")
    pr_details = _pull_request_details(report.team_id, pr_url) if pr_url is not None else None

    with transaction.atomic():
        locked_report = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        assignment = SignalReportAssignment.all_teams.select_for_update().filter(report_id=locked_report.id).first()
        before = assignment_snapshot(assignment)

        if release:
            if assignment is None:
                return None
            if assignment.actor_kind and not actor_owns_assignment(assignment, actor):
                raise ReportClaimConflict("Only the current assignee can release this report.")
            _clear_actor(assignment)
        else:
            if locked_report.status not in CLAIMABLE_REPORT_STATUSES:
                raise ReportClaimConflict(f"Reports with status '{locked_report.status}' cannot be claimed.")
            if assignment is None:
                assignment = SignalReportAssignment(
                    team_id=locked_report.team_id,
                    report_id=locked_report.id,
                )
            if not actor_owns_assignment(assignment, actor):
                _set_actor(assignment, actor)
            if pr_details is not None:
                assignment.pr_url = pr_details.url
                assignment.repository = pr_details.repository
                assignment.pr_number = pr_details.number
                assignment.pr_state = pr_details.state
                assignment.pr_merged = pr_details.merged

        after = assignment_snapshot(assignment)
        if before == after:
            return assignment

        assignment.save()
        _apply_pr_report_state(locked_report, assignment.pr_state)
        changes: list[Change] = []
        if before["assignee"] != after["assignee"]:
            changes.append(
                Change(
                    type="SignalReport",
                    action="changed",
                    field="assignee",
                    before=before["assignee"],
                    after=after["assignee"],
                )
            )
        if before["implementation_pr"] != after["implementation_pr"]:
            changes.append(
                Change(
                    type="SignalReport",
                    action="changed",
                    field="implementation_pr",
                    before=before["implementation_pr"],
                    after=after["implementation_pr"],
                )
            )
        log_activity(
            organization_id=None,
            team_id=locked_report.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=locked_report.id,
            scope="SignalReport",
            activity="assignment_changed",
            detail=Detail(name=locked_report.title, changes=changes),
        )
        return assignment


def update_assignments_for_pull_request(
    *,
    team_ids: list[int],
    repository: str,
    pr_number: int,
    pr_state: str,
) -> int:
    """Apply a scoped GitHub webhook state to every report linked to the PR."""
    if not team_ids:
        return 0
    normalized_repository = repository.lower()
    updated = 0
    with transaction.atomic():
        assignments = list(
            SignalReportAssignment.all_teams.select_for_update()
            .select_related("report")
            .filter(report__team_id__in=team_ids, repository=normalized_repository, pr_number=pr_number)
        )
        for assignment in assignments:
            merged = pr_state == SignalReportAssignment.PrState.MERGED
            changed = assignment.pr_state != pr_state or assignment.pr_merged != merged
            assignment.pr_state = pr_state
            assignment.pr_merged = merged
            if changed:
                assignment.save(update_fields=["pr_state", "pr_merged", "updated_at"])
            _apply_pr_report_state(assignment.report, pr_state)
            updated += 1
    return updated
