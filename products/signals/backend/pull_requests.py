from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.report_content_gates import team_report_monitoring_enabled

if TYPE_CHECKING:
    from products.signals.backend.implementation_pr import ImplementationPr
    from products.signals.backend.report_assignments import PullRequestDetails

logger = structlog.get_logger(__name__)

PARTICIPANT_REFRESH_DEDUPE_SECONDS = 60


class PullRequestStateSource(StrEnum):
    GITHUB = "github"
    TASK_OUTPUT = "task_output"
    LEGACY_ASSIGNMENT = "legacy_assignment"


def schedule_participant_refresh(pr: SignalReportPullRequest) -> None:
    from products.signals.backend.tasks import refresh_pull_request_participants

    if pr.state == SignalReportPullRequest.State.MERGED and pr.participants_synced_at is None:

        def enqueue() -> None:
            key = f"signals:participant-refresh:{pr.id}"
            claimed = False
            try:
                claimed = cache.add(key, True, timeout=PARTICIPANT_REFRESH_DEDUPE_SECONDS)
                if not claimed:
                    return
            except Exception:
                logger.exception("signals_participant_refresh_dedupe_failed", team_id=pr.team_id, pr_id=str(pr.id))
            try:
                refresh_pull_request_participants.delay(
                    team_id=pr.team_id, repository=pr.repository, pr_number=pr.number
                )
            except Exception:
                if claimed:
                    try:
                        cache.delete(key)
                    except Exception:
                        logger.exception(
                            "signals_participant_refresh_dedupe_cleanup_failed",
                            team_id=pr.team_id,
                            pr_id=str(pr.id),
                        )
                logger.exception("signals_participant_refresh_enqueue_failed", team_id=pr.team_id, pr_id=str(pr.id))

        transaction.on_commit(enqueue)


def reconcile_reports_for_pull_request(*, team_id: int, pr_id: str) -> None:
    from products.signals.backend.implementation_pr import report_ids_for_implementation_pr
    from products.signals.backend.supersession import schedule_report_replacements

    pr = SignalReportPullRequest.objects.for_team(team_id).get(id=pr_id)
    report_ids = report_ids_for_implementation_pr(team_id=team_id, repository=pr.repository, pr_number=pr.number)
    with transaction.atomic():
        reports = (
            SignalReport.objects.select_for_update(no_key=True)
            .filter(team_id=team_id, id__in=report_ids)
            .order_by("id")
        )
        for report in reports:
            apply_report_completion(report)
            schedule_report_replacements(team_id, str(report.id))


def completion_state(states: Sequence[str]) -> str | None:
    if not states or any(state not in {"closed", "merged"} for state in states):
        return None
    return "merged" if "merged" in states else "closed"


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
    previous_state = pr.state
    update_fields: list[str] = []
    if pr.state != SignalReportPullRequest.State.MERGED and details.state != SignalReportPullRequest.State.UNKNOWN:
        # Imported/task snapshots must not overwrite a state already verified with GitHub.
        if state_source == PullRequestStateSource.GITHUB or pr.checked_at is None:
            pr.state = details.state
            if state_source == PullRequestStateSource.GITHUB:
                pr.checked_at = timezone.now()
            update_fields.extend(["state", "checked_at"])
    if pr.state == SignalReportPullRequest.State.MERGED and pr.merged_at is None and details.merged_at is not None:
        pr.merged_at = details.merged_at
        update_fields.append("merged_at")
    if update_fields:
        pr.save(update_fields=[*update_fields, "updated_at"])
        # Wait for the complete PR batch and release its locks before locking shared reports.
        transaction.on_commit(partial(reconcile_reports_for_pull_request, team_id=report.team_id, pr_id=str(pr.id)))
        if state_source != PullRequestStateSource.LEGACY_ASSIGNMENT:
            from products.signals.backend.inbox_push_notifications import schedule_pull_request_ready_push

            schedule_pull_request_ready_push(pr, previous_state=previous_state)
    links = SignalReportArtefact.objects.filter(
        team_id=report.team_id,
        report_id=report.id,
        pull_request_id=pr.id,
        claim_id=claim_id,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
    )
    new_link = not links.exists()
    if new_link:
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
            and report.status
            in {SignalReport.Status.RESOLVED, SignalReport.Status.CLOSED, SignalReport.Status.MONITORING}
            and pr.state not in {SignalReportPullRequest.State.MERGED, SignalReportPullRequest.State.CLOSED}
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
            from products.signals.backend.pull_request_label import schedule_pull_request_label
            from products.signals.backend.reviewer_pr_ready import schedule_open_pull_request_ready

            schedule_open_pull_request_ready(
                team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
            )
            schedule_pull_request_label(
                team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
            )
    if (
        actor.kind == "task"
        and actor.task_id
        and (new_link or state_source == PullRequestStateSource.TASK_OUTPUT)
        and state_source != PullRequestStateSource.LEGACY_ASSIGNMENT
        and pr.state
        in {
            SignalReportPullRequest.State.DRAFT,
            SignalReportPullRequest.State.OPEN,
            SignalReportPullRequest.State.UNKNOWN,
        }
    ):
        from products.signals.backend.support_writeback import task_can_write_support_ticket_update

        if task_can_write_support_ticket_update(
            team_id=report.team_id, report_id=str(report.id), task_id=actor.task_id, pr_url=pr.url
        ):
            from products.signals.backend.tasks import write_pull_request_to_support_tickets

            transaction.on_commit(
                partial(
                    write_pull_request_to_support_tickets.delay, report.team_id, str(report.id), pr.url, actor.task_id
                ),
                robust=True,
            )
    if notify_reviewers and state_source != PullRequestStateSource.LEGACY_ASSIGNMENT:
        # Every verified PR refresh can change paths, ownership, membership, or linked identities.
        # The assignment worker is bounded and replaces only the owners named by its own latest
        # provenance record, so repeated webhook deliveries are safe reassessment triggers.
        from products.signals.backend.reviewer_pr_assignment import schedule_reviewer_pr_assignment

        schedule_reviewer_pr_assignment(
            team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
        )
    if state_source != PullRequestStateSource.LEGACY_ASSIGNMENT:
        schedule_participant_refresh(pr)
    return pr


def _repair_missing_merge_times(report: SignalReport, prs: Sequence["ImplementationPr"]) -> None:
    from products.signals.backend.report_assignments import MAX_PR_NUMBER, MAX_REPOSITORY_LENGTH, PullRequestDetails
    from products.signals.backend.tasks import refresh_pull_request_review_decision

    for pr in prs:
        if pr.state != "merged" or pr.merged_at is not None:
            continue
        parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
        if parsed is None or not 0 < parsed.number <= MAX_PR_NUMBER or len(parsed.repository) > MAX_REPOSITORY_LENGTH:
            continue
        stored = link_pull_request(
            report=report,
            details=PullRequestDetails(
                url=pr.url, repository=parsed.repository.lower(), number=parsed.number, state="merged", merged=True
            ),
            actor=ArtefactAttribution.from_task(pr.task_id) if pr.task_id else ArtefactAttribution.system(),
            claim_id=pr.claim_id,
            state_source=PullRequestStateSource.TASK_OUTPUT,
            notify_reviewers=False,
        )
        transaction.on_commit(
            partial(
                refresh_pull_request_review_decision.delay,
                team_id=report.team_id,
                repository=stored.repository,
                pr_number=stored.number,
            )
        )


def apply_report_completion(report: SignalReport) -> None:
    from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
    from products.signals.backend.report_assignments import _apply_pr_report_state
    from products.signals.backend.supersession import pending_replacement

    if pending_replacement(report.team_id, str(report.id), using="default") is not None:
        return

    prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id, using="default").get(
        str(report.id), []
    )
    state = completion_state([pr.state for pr in prs])
    if state is not None:
        merged_prs = [pr for pr in prs if pr.state == "merged"]
        merge_times = [pr.merged_at for pr in merged_prs if pr.merged_at is not None]
        merged_at = max(merge_times) if merge_times and len(merge_times) == len(merged_prs) else None
        _apply_pr_report_state(report, state, merged_at=merged_at)
        if (
            state == "merged"
            and merged_at is None
            and report.status
            in {SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT, SignalReport.Status.FAILED}
            and team_report_monitoring_enabled(report.team_id)
        ):
            _repair_missing_merge_times(report, prs)


def import_report_pull_requests(report: SignalReport, *, notify_reviewers: bool = False) -> None:
    from posthog.models.github_integration_base import GitHubIntegrationBase

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


def update_pull_request_state(
    *, team_id: int, repository: str, number: int, state: str, merged_at: datetime | None = None
) -> int:
    report_ids = SignalReportArtefact.objects.filter(
        team_id=team_id,
        pull_request__team_id=team_id,
        pull_request__repository=repository.lower(),
        pull_request__number=number,
    ).values_list("report_id", flat=True)
    with transaction.atomic():
        reports = list(
            SignalReport.objects.select_for_update(no_key=True)
            .filter(team_id=team_id, id__in=report_ids)
            .order_by("id")
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
        previous_state = pr.state
        if pr.state != SignalReportPullRequest.State.MERGED:
            pr.state = state
        update_fields = ["state", "checked_at", "updated_at"]
        if state == SignalReportPullRequest.State.MERGED and pr.merged_at is None and merged_at is not None:
            pr.merged_at = merged_at
            update_fields.append("merged_at")
        pr.checked_at = timezone.now()
        pr.save(update_fields=update_fields)
        schedule_participant_refresh(pr)
        from products.signals.backend.inbox_push_notifications import schedule_pull_request_ready_push

        schedule_pull_request_ready_push(pr, previous_state=previous_state)
        for report in reports:
            apply_report_completion(report)
        return len(reports)


def update_pull_request_review_decision(
    *, team_id: int, repository: str, number: int, review_decision: str | None
) -> int:
    if review_decision is not None and review_decision not in SignalReportPullRequest.ReviewDecision.values:
        return 0
    return (
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(repository=repository.lower(), number=number)
        .update(review_decision=review_decision, updated_at=timezone.now())
    )
