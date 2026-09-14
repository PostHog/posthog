from collections.abc import Mapping, Sequence
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest

if TYPE_CHECKING:
    from products.signals.backend.implementation_pr import ImplementationPr
    from products.signals.backend.report_assignments import PullRequestDetails

logger = structlog.get_logger(__name__)

# The states that finish a report: merged resolves it, closed suppresses it.
TERMINAL_PR_STATES = frozenset({SignalReportPullRequest.State.MERGED, SignalReportPullRequest.State.CLOSED})


class PullRequestStateSource(StrEnum):
    GITHUB = "github"
    TASK_OUTPUT = "task_output"
    LEGACY_ASSIGNMENT = "legacy_assignment"


def pull_request_state_from_status(status: Mapping[str, Any]) -> str:
    """Map a GitHub pull request payload onto a stored state.

    GitHub reports a merged pull request as closed, so the merge flag is read first.
    """
    if status.get("merged"):
        return SignalReportPullRequest.State.MERGED
    if status.get("state") == "closed":
        return SignalReportPullRequest.State.CLOSED
    if status.get("draft"):
        return SignalReportPullRequest.State.DRAFT
    if status.get("state") == "open":
        return SignalReportPullRequest.State.OPEN
    return SignalReportPullRequest.State.UNKNOWN


def reconcile_reports_for_pull_request(*, team_id: int, pr_id: str) -> None:
    from products.signals.backend.implementation_pr import report_ids_for_implementation_pr

    pr = SignalReportPullRequest.objects.for_team(team_id).get(id=pr_id)
    report_ids = report_ids_for_implementation_pr(team_id=team_id, repository=pr.repository, pr_number=pr.number)
    with transaction.atomic():
        reports = SignalReport.objects.select_for_update().filter(team_id=team_id, id__in=report_ids).order_by("id")
        for report in reports:
            apply_report_completion(report)


def completion_state(prs: Sequence["ImplementationPr"]) -> str | None:
    """The state that finishes the report, or None while any pull request could still be live.

    Only GitHub can end a report. A task run writes its own `pr_merged` into its output, and that
    claim is wrong whenever the pull request was closed unmerged or is still open, so a state
    nobody read back from GitHub holds the report open until the verification job reads it.
    """
    if not prs or any(pr.state not in TERMINAL_PR_STATES or not pr.confirmed for pr in prs):
        return None
    return (
        SignalReportPullRequest.State.MERGED
        if any(pr.state == SignalReportPullRequest.State.MERGED for pr in prs)
        else SignalReportPullRequest.State.CLOSED
    )


def link_pull_request(
    *,
    report: SignalReport,
    details: "PullRequestDetails",
    actor: ArtefactAttribution,
    claim_id: str | None,
    state_source: PullRequestStateSource = PullRequestStateSource.GITHUB,
    notify_reviewers: bool = True,
) -> SignalReportPullRequest:
    if (
        claim_id
        and not SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            id=claim_id,
            type="work_claim",
        ).exists()
    ):
        raise ValueError("Claim must belong to the report and team.")
    pr, _ = SignalReportPullRequest.objects.for_team(report.team_id).get_or_create(
        team_id=report.team_id,
        repository=details.repository,
        number=details.number,
        defaults={"url": details.url},
    )
    pr = SignalReportPullRequest.objects.for_team(report.team_id).select_for_update().get(id=pr.id)
    # Only a merge GitHub confirmed is terminal. A merge a task run claimed stays correctable, or a
    # wrong claim would outlive every later event that contradicts it.
    confirmed_merge = pr.state == SignalReportPullRequest.State.MERGED and pr.checked_at is not None
    if not confirmed_merge and details.state != SignalReportPullRequest.State.UNKNOWN:
        # Imported/task snapshots must not overwrite a state already verified with GitHub.
        if state_source == PullRequestStateSource.GITHUB or pr.checked_at is None:
            pr.state = details.state
            if state_source == PullRequestStateSource.GITHUB:
                pr.checked_at = timezone.now()
            pr.save(update_fields=["state", "checked_at", "updated_at"])
            # Wait for the complete PR batch and release its locks before locking shared reports.
            transaction.on_commit(partial(reconcile_reports_for_pull_request, team_id=report.team_id, pr_id=str(pr.id)))
    links = SignalReportArtefact.objects.filter(
        team_id=report.team_id,
        report_id=report.id,
        pull_request_id=pr.id,
        claim_id=claim_id,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
    )
    if not links.exists():
        link = SignalReportArtefact.add_log(
            team_id=report.team_id,
            report_id=str(report.id),
            content=PullRequestLink(url=pr.url),
            attribution=actor,
            claim_id=claim_id,
        )
        link.pull_request = pr
        link.save(update_fields=["pull_request"])
        if (
            state_source != PullRequestStateSource.LEGACY_ASSIGNMENT
            and report.status == SignalReport.Status.RESOLVED
            and pr.state not in TERMINAL_PR_STATES
        ):
            report.save(update_fields=report.transition_to(SignalReport.Status.READY))
        if (
            notify_reviewers
            and not SignalReportArtefact.objects.filter(
                team_id=report.team_id, report_id=report.id, pull_request_id=pr.id
            )
            .exclude(id=link.id)
            .exists()
        ):
            from products.signals.backend.reviewer_pr_assignment import schedule_reviewer_pr_assignment
            from products.signals.backend.reviewer_pr_ready import schedule_open_pull_request_ready

            schedule_reviewer_pr_assignment(
                team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
            )
            schedule_open_pull_request_ready(
                team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
            )
    return pr


def apply_report_completion(report: SignalReport) -> None:
    from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
    from products.signals.backend.report_assignments import _apply_pr_report_state

    prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id).get(str(report.id), [])
    state = completion_state(prs)
    if state is not None:
        _apply_pr_report_state(report, state)
        return
    schedule_pull_request_verification(team_id=report.team_id, prs=prs)


def schedule_pull_request_verification(*, team_id: int, prs: Sequence["ImplementationPr"]) -> None:
    """Queue a GitHub read for every pull request that claims a terminal state nobody verified.

    Queued on commit so the GitHub calls run on a worker rather than inside the transaction that
    holds the report locks. `robust=True` keeps a broker outage from failing the write that
    committed: the next pull request event queues the read again.
    """
    from products.signals.backend.tasks import verify_implementation_pr_state

    for pr in prs:
        if pr.confirmed or pr.state not in TERMINAL_PR_STATES:
            continue
        transaction.on_commit(
            partial(verify_implementation_pr_state.delay, team_id=team_id, pr_url=pr.url),
            robust=True,
        )


def pull_request_state_confirmed(*, team_id: int, pr_url: str) -> bool:
    """True when a GitHub read already stored a state for this pull request."""
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        return False
    return (
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(repository=parsed.repository.lower(), number=parsed.number, checked_at__isnull=False)
        .exists()
    )


def _stored_merge_exists(*, team_id: int, repository: str, pr_number: int, confirmed: bool) -> bool:
    return (
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(
            repository=repository,
            number=pr_number,
            state=SignalReportPullRequest.State.MERGED,
            checked_at__isnull=not confirmed,
        )
        .exists()
    )


def verify_pull_request_state(
    *, team_id: int, pr_url: str, source: str | None = None, priority: Priority | None = None
) -> str | None:
    """Read a pull request state from GitHub and store it as confirmed. Returns the stored state.

    Returns None when the state could not be read, which leaves every report holding this pull
    request open. A report resolved on a merge GitHub then contradicts is reopened here, because no
    later event reaches a resolved report to correct it. A report suppressed on an unconfirmed close
    is left alone: suppression is also what a person does by hand, and undoing theirs is worse than
    leaving a stale one.
    """
    from products.signals.backend.report_assignments import _pull_request_details, update_assignments_for_pull_request

    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        return None
    repository, pr_number = parsed.repository.lower(), parsed.number
    state = _pull_request_details(team_id, pr_url, source=source, priority=priority).state
    if state == SignalReportPullRequest.State.UNKNOWN:
        return None
    claimed_merge = state not in TERMINAL_PR_STATES and _stored_merge_exists(
        team_id=team_id, repository=repository, pr_number=pr_number, confirmed=False
    )
    update_assignments_for_pull_request(team_ids=[team_id], repository=repository, pr_number=pr_number, pr_state=state)
    # A merge webhook can land between the read above and this write, where it wins the merge guard
    # in `update_pull_request_state`. Reopening on the claim read earlier would then undo that merge.
    if claimed_merge and not _stored_merge_exists(
        team_id=team_id, repository=repository, pr_number=pr_number, confirmed=True
    ):
        reopen_reports_resolved_without_merge(team_id=team_id, repository=repository, pr_number=pr_number)
    return state


def reopen_reports_resolved_without_merge(*, team_id: int, repository: str, pr_number: int) -> int:
    """Move every report this pull request resolved back to ready. Returns how many moved."""
    from products.signals.backend.implementation_pr import report_ids_for_implementation_pr

    report_ids = report_ids_for_implementation_pr(team_id=team_id, repository=repository, pr_number=pr_number)
    with transaction.atomic():
        reports = list(
            SignalReport.objects.select_for_update()
            .filter(team_id=team_id, id__in=report_ids, status=SignalReport.Status.RESOLVED)
            .order_by("id")
        )
        for report in reports:
            logger.info(
                "signals.pr_verification.reopened_report",
                team_id=team_id,
                report_id=str(report.id),
                repository=repository,
                pr_number=pr_number,
            )
            report.save(update_fields=report.transition_to(SignalReport.Status.READY))
        return len(reports)


def import_report_pull_requests(report: SignalReport, *, notify_reviewers: bool = False) -> None:
    from products.signals.backend.artefact_schemas import WorkClaim
    from products.signals.backend.models import SignalReportAssignment
    from products.signals.backend.report_assignments import PullRequestDetails, assignment_actor

    assignment = SignalReportAssignment.all_teams.filter(team_id=report.team_id, report_id=report.id).first()
    legacy_claim_id = None
    if assignment is not None and assignment.actor_kind:
        history = SignalReportArtefact.objects.filter(team_id=report.team_id, report_id=report.id, type="work_claim")
        if not history.exists():
            SignalReportArtefact.objects.create(
                id=assignment.id,
                team_id=report.team_id,
                report_id=report.id,
                type="work_claim",
                content=WorkClaim(
                    display_name=claim_display_name(report, assignment_actor(assignment))
                ).model_dump_json(),
                actor_kind=assignment.actor_kind,
                created_by_id=assignment.actor_user_id,
                task_id=assignment_actor(assignment).task_id,
                actor_agent=assignment.actor_agent,
            )
            SignalReportArtefact.objects.filter(id=assignment.id, team_id=report.team_id).update(
                created_at=assignment.claimed_at or assignment.created_at,
            )
        if history.filter(id=assignment.id).exists():
            legacy_claim_id = str(assignment.id)
    candidates: list[tuple[str, str, ArtefactAttribution, str | None]] = []
    if assignment is not None and assignment.pr_url:
        candidates.append(
            (
                assignment.pr_url,
                "merged" if assignment.pr_merged else assignment.pr_state or "unknown",
                assignment_actor(assignment),
                legacy_claim_id,
            )
        )
    for url, state, actor, claim_id in candidates:
        parsed = GitHubIntegrationBase.parse_pull_request_url(url)
        if parsed is None or not 0 < parsed.number <= 2**63 - 1 or len(parsed.repository) > 200:
            continue
        if SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            pull_request__repository=parsed.repository.lower(),
            pull_request__number=parsed.number,
            pull_request__team_id=report.team_id,
        ).exists():
            continue
        pr = link_pull_request(
            report=report,
            details=PullRequestDetails(
                url=url,
                repository=parsed.repository.lower(),
                number=parsed.number,
                state=state if state in SignalReportPullRequest.State.values else "unknown",
                merged=state == "merged",
            ),
            actor=actor,
            claim_id=claim_id,
            state_source=PullRequestStateSource.LEGACY_ASSIGNMENT,
            notify_reviewers=notify_reviewers,
        )
        if assignment is not None and url == assignment.pr_url and actor.kind != assignment.actor_kind:
            # A missing legacy principal must not turn an external attachment into trusted system work.
            SignalReportArtefact.objects.filter(
                team_id=report.team_id,
                report_id=report.id,
                pull_request_id=pr.id,
                claim_id=claim_id,
            ).update(actor_kind=assignment.actor_kind, actor_agent=assignment.actor_agent)


def update_pull_request_state(*, team_id: int, repository: str, number: int, state: str) -> int:
    report_ids = SignalReportArtefact.objects.filter(
        team_id=team_id,
        pull_request__team_id=team_id,
        pull_request__repository=repository.lower(),
        pull_request__number=number,
    ).values_list("report_id", flat=True)
    with transaction.atomic():
        reports = list(
            SignalReport.objects.select_for_update().filter(team_id=team_id, id__in=report_ids).order_by("id")
        )
        pr = (
            SignalReportPullRequest.objects.for_team(team_id)
            .select_for_update()
            .filter(
                repository=repository.lower(),
                number=number,
            )
            .first()
        )
        if pr is None:
            return 0
        if pr.state != SignalReportPullRequest.State.MERGED or pr.checked_at is None:
            pr.state = state
        pr.checked_at = timezone.now()
        pr.save(update_fields=["state", "checked_at", "updated_at"])
        for report in reports:
            apply_report_completion(report)
        return len(reports)
