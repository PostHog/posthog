from collections.abc import Sequence
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest

if TYPE_CHECKING:
    from products.signals.backend.report_assignments import PullRequestDetails


class PullRequestStateSource(StrEnum):
    GITHUB = "github"
    TASK_OUTPUT = "task_output"
    LEGACY_ASSIGNMENT = "legacy_assignment"


def reconcile_reports_for_pull_request(*, team_id: int, pr_id: str) -> None:
    from products.signals.backend.implementation_pr import report_ids_for_implementation_pr

    pr = SignalReportPullRequest.objects.for_team(team_id).get(id=pr_id)
    report_ids = report_ids_for_implementation_pr(team_id=team_id, repository=pr.repository, pr_number=pr.number)
    with transaction.atomic():
        reports = SignalReport.objects.select_for_update().filter(team_id=team_id, id__in=report_ids).order_by("id")
        for report in reports:
            apply_report_completion(report)


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
    if pr.state != SignalReportPullRequest.State.MERGED and details.state != SignalReportPullRequest.State.UNKNOWN:
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

    states = [
        pr.state
        for pr in fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id).get(str(report.id), [])
    ]
    state = completion_state(states)
    if state is not None:
        _apply_pr_report_state(report, state)


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
        if pr.state != SignalReportPullRequest.State.MERGED:
            pr.state = state
        pr.checked_at = timezone.now()
        pr.save(update_fields=["state", "checked_at", "updated_at"])
        for report in reports:
            apply_report_completion(report)
        return len(reports)
