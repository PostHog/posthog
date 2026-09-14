"""Claim and pull request lifecycle for signal reports."""

from __future__ import annotations

from typing import TypedDict

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration
from posthog.models.user import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import TaskRunArtefact, WorkClaim, WorkRelease
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
)
from products.signals.backend.pull_requests import (
    PullRequestStateSource,
    apply_report_completion,
    import_report_pull_requests,
    link_pull_request,
    update_pull_request_state,
)
from products.signals.backend.report_claims import ReportClaim, actor_owns_claim, claim_from_artefact, get_active_claim
from products.tasks.backend.facade import api as tasks_facade

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
        SignalReport.Status.CANDIDATE,
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.FAILED,
    }
)


class ReportClaimConflict(Exception):
    pass


class InvalidPullRequestUrl(Exception):
    pass


class AssigneeSnapshot(TypedDict):
    kind: str | None
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


def assignment_snapshot(report: SignalReport, assignment: ReportClaim | None) -> AssignmentSnapshot:
    assignee: AssigneeSnapshot | None = None
    if assignment is not None:
        assignee = AssigneeSnapshot(
            kind=assignment.actor_kind,
            user_id=assignment.actor_user_id,
            task_id=str(assignment.actor_task_id) if assignment.actor_task_id else None,
            agent=assignment.actor_agent,
            claimed_at=assignment.claimed_at.isoformat(),
        )
    from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports

    implementation_pr: PullRequestSnapshot | None = None
    pr = fetch_implementation_pr_state_for_reports([str(report.id)], team_id=report.team_id).get(str(report.id))
    if pr is not None:
        parsed = GitHubIntegration.parse_pull_request_url(pr.url)
        implementation_pr = {
            "url": pr.url,
            "repository": parsed.repository if parsed else None,
            "number": parsed.number if parsed else None,
            "state": pr.state,
            "merged": pr.merged,
        }
    return {"assignee": assignee, "implementation_pr": implementation_pr}


def create_claim(report: SignalReport, actor: ArtefactAttribution) -> ReportClaim:
    claim = SignalReportArtefact.add_log(
        team_id=report.team_id,
        report_id=str(report.id),
        content=WorkClaim(display_name=claim_display_name(report, actor)),
        attribution=actor,
    )
    if actor.task_id:
        associations = SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            type="task_run",
            task_id=actor.task_id,
        )
        if not associations.exists():
            SignalReportArtefact.add_log(
                team_id=report.team_id,
                report_id=str(report.id),
                content=TaskRunArtefact(task_id=actor.task_id, product="tasks", type="agent_run"),
                attribution=actor,
                claim_id=str(claim.id),
            )
        else:
            associations.filter(claim__isnull=True).update(claim=claim)
    return claim_from_artefact(claim)


def assignment_actor(assignment: SignalReportAssignment) -> ArtefactAttribution:
    if assignment.actor_kind == "task" and assignment.actor_task_id:
        if tasks_facade.task_exists(str(assignment.actor_task_id), assignment.team_id):
            return ArtefactAttribution.from_task(str(assignment.actor_task_id))
        return ArtefactAttribution.system()
    if assignment.actor_kind == "agent" and assignment.actor_user_id and assignment.actor_agent:
        return ArtefactAttribution.from_agent(assignment.actor_user_id, assignment.actor_agent)
    if assignment.actor_kind == "user" and assignment.actor_user_id:
        return ArtefactAttribution.from_user(assignment.actor_user_id)
    return ArtefactAttribution.system()


def release_claim(claim: ReportClaim, actor: ArtefactAttribution, *, takeover: bool = False) -> None:
    if not SignalReportArtefact.objects.filter(team_id=claim.team_id, id=claim.claim_id).exists():
        import_report_pull_requests(SignalReport.objects.get(team_id=claim.team_id, id=claim.report_id))
    SignalReportArtefact.add_log(
        team_id=claim.team_id,
        report_id=str(claim.report_id),
        content=WorkRelease(reason="taken_over" if takeover else "released"),
        attribution=actor,
        claim_id=str(claim.claim_id),
    )


def claim_report_for_task(*, team_id: int, report_id: str, task_id: str) -> ReportClaim:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(id=report_id, team_id=team_id)
        import_report_pull_requests(report)
        claim = get_active_claim(team_id=team_id, report_id=report_id)
        actor = ArtefactAttribution.from_task(task_id)
        if claim is not None and not actor_owns_claim(claim, actor):
            raise ReportClaimConflict("This report already has an active claim.")
        return claim or create_claim(report, actor)


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


def sync_task_pull_request_to_assignments(
    *,
    team_id: int,
    task_id: str,
    pr_url: str,
    pr_state: str | None = None,
    pr_merged: bool = False,
) -> int:
    """Copy a task-run PR onto reports still owned by that task, or without an explicit PR."""
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None or not 0 < parsed.number <= MAX_PR_NUMBER:
        return 0
    repository = parsed.repository.lower()
    if len(repository) > MAX_REPOSITORY_LENGTH:
        return 0

    state = pr_state if pr_state in SignalReportAssignment.PrState.values else SignalReportAssignment.PrState.UNKNOWN
    merged = pr_merged or state == SignalReportAssignment.PrState.MERGED
    if merged:
        state = SignalReportAssignment.PrState.MERGED

    report_ids = list(
        SignalReport.objects.filter(team_id=team_id)
        .filter(SignalReport.reports_for_task_filter(task_id))
        .values_list("id", flat=True)
    )
    if not report_ids:
        return 0

    actor = ArtefactAttribution.from_task(task_id)
    with transaction.atomic():
        reports = list(
            SignalReport.objects.select_for_update().filter(team_id=team_id, id__in=report_ids).order_by("id")
        )
        for report in reports:
            import_report_pull_requests(report, notify_reviewers=True)
            historical = (
                SignalReportArtefact.objects.filter(
                    team_id=team_id,
                    report_id=report.id,
                    type="work_claim",
                    task_id=task_id,
                )
                .order_by("-created_at", "-id")
                .first()
            )
            claim_id = str(historical.id) if historical else None
            link_pull_request(
                report=report,
                details=PullRequestDetails(
                    url=pr_url, repository=repository, number=parsed.number, state=state, merged=merged
                ),
                actor=actor,
                claim_id=claim_id,
                state_source=PullRequestStateSource.TASK_OUTPUT,
            )
        return len(reports)


def _apply_pr_report_state(report: SignalReport, pr_state: str | None) -> None:
    target = None
    if pr_state == SignalReportAssignment.PrState.MERGED:
        target = SignalReport.Status.RESOLVED
    elif pr_state == SignalReportAssignment.PrState.CLOSED:
        target = SignalReport.Status.SUPPRESSED
    if target is None or report.status == target:
        return
    # Resolving a report closes its own pull request, and GitHub reports that close as an unmerged
    # close. Suppressing on it would undo the resolution moments after the person made it.
    if target == SignalReport.Status.SUPPRESSED and report.status == SignalReport.Status.RESOLVED:
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
    # GitHub already reports this pull request as closed or merged. Without this marker the
    # dismissal receiver queues a redundant close for every report that shares the pull request.
    report._status_from_pr_state = True  # type: ignore[attr-defined]
    report.save(update_fields=updated_fields)


def claim_report(
    *,
    report: SignalReport,
    actor: ArtefactAttribution,
    user: User,
    was_impersonated: bool,
    pr_url: str | None = None,
    release: bool = False,
    pull_requests: list[str] | None = None,
    claim_id: str | None = None,
    takeover: bool = False,
) -> ReportClaim | None:
    """Claim, release, or attach a PR to one report and return the current assignment."""
    if release and (pr_url or pull_requests or takeover):
        raise ReportClaimConflict("Release cannot be combined with pull requests or takeover.")
    urls = list(dict.fromkeys(([pr_url] if pr_url else []) + (pull_requests or [])))
    details = sorted(
        (_pull_request_details(report.team_id, url) for url in urls), key=lambda pr: (pr.repository, pr.number)
    )

    with transaction.atomic():
        locked_report = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        import_report_pull_requests(locked_report, notify_reviewers=True)
        assignment = get_active_claim(team_id=report.team_id, report_id=report.id)
        before = assignment_snapshot(locked_report, assignment)
        if claim_id and (assignment is None or str(assignment.claim_id) != claim_id):
            raise ReportClaimConflict("This claim is no longer active.")
        if claim_id and assignment is not None and not actor_owns_claim(assignment, actor):
            raise ReportClaimConflict("This claim belongs to another actor.")

        if release:
            if assignment is None:
                return None
            if assignment.actor_kind and not actor_owns_claim(assignment, actor):
                raise ReportClaimConflict("Only the current assignee can release this report.")
            release_claim(assignment, actor)
            assignment = None
        else:
            if locked_report.status not in CLAIMABLE_REPORT_STATUSES:
                existing_prs = set(
                    SignalReportArtefact.objects.filter(
                        team_id=report.team_id, report_id=report.id, pull_request__isnull=False
                    ).values_list("pull_request__repository", "pull_request__number")
                )
                if (
                    not takeover
                    and assignment is not None
                    and actor_owns_claim(assignment, actor)
                    and all((pr.repository, pr.number) in existing_prs for pr in details)
                ):
                    return assignment
                raise ReportClaimConflict(f"Reports with status '{locked_report.status}' cannot be claimed.")
            if assignment is not None and not actor_owns_claim(assignment, actor):
                if not takeover:
                    raise ReportClaimConflict(
                        "This report already has an active claim. Use takeover=true to take ownership."
                    )
                release_claim(assignment, actor, takeover=True)
                assignment = None
            if assignment is None:
                assignment = create_claim(locked_report, actor)

        for pr_details in details:
            link_pull_request(
                report=locked_report,
                details=pr_details,
                actor=actor,
                claim_id=str(assignment.claim_id) if assignment else None,
            )
        if details:
            apply_report_completion(locked_report)

        after = assignment_snapshot(locked_report, assignment)
        if before == after:
            return assignment

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
    from products.signals.backend.implementation_pr import (
        fetch_implementation_prs_for_reports,
        report_ids_for_implementation_pr,
    )
    from products.signals.backend.pull_requests import import_report_pull_requests

    updated = 0
    for team_id in sorted(set(team_ids)):
        report_ids = report_ids_for_implementation_pr(team_id=team_id, repository=repository, pr_number=pr_number)
        with transaction.atomic():
            reports = SignalReport.objects.select_for_update().filter(team_id=team_id, id__in=report_ids).order_by("id")
            for report in reports:
                import_report_pull_requests(report, notify_reviewers=True)
                for pr in fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id).get(
                    str(report.id), []
                ):
                    parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
                    if (
                        parsed
                        and parsed.repository.lower() == repository.lower()
                        and parsed.number == pr_number
                        and pr.task_id
                    ):
                        link_pull_request(
                            report=report,
                            details=PullRequestDetails(
                                url=pr.url,
                                repository=repository.lower(),
                                number=pr_number,
                                state=pr_state,
                                merged=pr_state == "merged",
                            ),
                            actor=ArtefactAttribution.from_task(pr.task_id),
                            claim_id=pr.claim_id,
                        )
            updated += update_pull_request_state(
                team_id=team_id, repository=repository, number=pr_number, state=pr_state
            )
    return updated
