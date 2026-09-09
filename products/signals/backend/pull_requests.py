from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.models import SignalPullRequest, SignalReport, SignalReportArtefact

if TYPE_CHECKING:
    from products.signals.backend.report_assignments import PullRequestDetails


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
    migrated: bool = False,
    notify_reviewers: bool = True,
) -> SignalPullRequest:
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
    pr, _ = SignalPullRequest.objects.for_team(report.team_id).get_or_create(
        team_id=report.team_id,
        repository=details.repository,
        number=details.number,
        defaults={"url": details.url},
    )
    pr = SignalPullRequest.objects.for_team(report.team_id).select_for_update().get(id=pr.id)
    if pr.state != SignalPullRequest.State.MERGED and details.state != SignalPullRequest.State.UNKNOWN:
        # Imported/task snapshots must not overwrite a state already verified with GitHub.
        if not migrated or pr.checked_at is None:
            pr.state = details.state
            if not migrated:
                pr.checked_at = timezone.now()
            pr.save(update_fields=["state", "checked_at", "updated_at"])
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
            content=PullRequestLink(url=pr.url, migrated=migrated),
            attribution=actor,
        )
        link.claim_id = claim_id
        link.pull_request = pr
        link.save(update_fields=["claim", "pull_request"])
        if (
            notify_reviewers
            and not SignalReportArtefact.objects.filter(
                team_id=report.team_id, report_id=report.id, pull_request_id=pr.id
            )
            .exclude(id=link.id)
            .exists()
        ):
            from products.signals.backend.reviewer_pr_assignment import schedule_reviewer_pr_assignment

            schedule_reviewer_pr_assignment(
                team_id=report.team_id, report_id=str(report.id), pr_url=pr.url, pr_state=pr.state
            )
    return pr


def apply_report_completion(report: SignalReport) -> None:
    from products.signals.backend.report_assignments import _apply_pr_report_state

    states = list(
        SignalPullRequest.objects.for_team(report.team_id)
        .filter(report_links__team_id=report.team_id, report_links__report_id=report.id)
        .values_list("state", flat=True)
        .distinct()
    )
    state = completion_state(states)
    if state is not None:
        _apply_pr_report_state(report, state)


def import_report_pull_requests(report: SignalReport, *, notify_reviewers: bool = False) -> None:
    from posthog.models.github_integration_base import GitHubIntegrationBase

    from products.signals.backend.implementation_pr import (
        fetch_legacy_implementation_pr_state_for_reports,
        pr_bearing_task_run_filter,
    )
    from products.signals.backend.models import SignalReportAssignment
    from products.signals.backend.report_assignments import PullRequestDetails, assignment_actor, ensure_claim
    from products.tasks.backend.facade import api as tasks_facade

    assignment = SignalReportAssignment.all_teams.filter(team_id=report.team_id, report_id=report.id).first()
    if assignment is not None and assignment.actor_kind:
        ensure_claim(assignment, migrated=True)
        assignment.save(update_fields=["claim"])
    candidates: list[tuple[str, str, ArtefactAttribution, str | None]] = []
    legacy = fetch_legacy_implementation_pr_state_for_reports([str(report.id)]).get(str(report.id))
    if legacy is not None:
        actor = (
            assignment_actor(assignment)
            if assignment and assignment.pr_url
            else (ArtefactAttribution.from_task(legacy.task_id) if legacy.task_id else ArtefactAttribution.system())
        )
        candidates.append(
            (legacy.url, legacy.state, actor, str(assignment.claim_id) if assignment and assignment.claim_id else None)
        )
    runs = SignalReport.associated_task_runs_for_reports(report_ids=[str(report.id)], product="signals").get(
        str(report.id), []
    )
    task_ids = {
        run.task_id
        for run in runs
        if run.type not in {"research", "repo_selection"} and not run.type.startswith("scout:")
    }
    task_prs = tasks_facade.get_pull_requests_for_tasks(report.team_id, task_ids, pr_bearing_task_run_filter())
    for task_id, prs in task_prs.items():
        for url, state in prs:
            task_claim_id = (
                str(assignment.claim_id)
                if assignment and assignment.claim_id and str(assignment.actor_task_id) == task_id
                else None
            )
            candidates.append((url, state, ArtefactAttribution.from_task(task_id), task_claim_id))
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
                state=state if state in SignalPullRequest.State.values else "unknown",
                merged=state == "merged",
            ),
            actor=actor,
            claim_id=claim_id,
            migrated=True,
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
    from products.signals.backend.models import SignalReportAssignment

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
            SignalPullRequest.objects.for_team(team_id)
            .select_for_update()
            .filter(
                repository=repository.lower(),
                number=number,
            )
            .first()
        )
        if pr is None:
            return 0
        if pr.state != SignalPullRequest.State.MERGED:
            pr.state = state
        pr.checked_at = timezone.now()
        pr.save(update_fields=["state", "checked_at", "updated_at"])
        SignalReportAssignment.all_teams.filter(
            team_id=team_id, repository=repository.lower(), pr_number=number
        ).update(
            pr_state=pr.state,
            pr_merged=pr.state == SignalPullRequest.State.MERGED,
        )
        for report in reports:
            apply_report_completion(report)
        return len(reports)
