from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ImplementationDecision,
    ImplementationHandover,
    ImplementationReplacement,
    ImplementationTarget,
    TaskRunArtefact,
)
from products.signals.backend.implementation_pr import (
    _close_implementation_pr,
    fetch_implementation_prs_for_reports,
    implementation_pr_needed_by_another_report,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_claims import get_active_claim
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)
MAX_HANDOVER_ATTEMPTS = 5
HANDOVER_LEASE_SECONDS = 300


@frozen
class ImplementationResearchContext:
    candidates: tuple[ImplementationTarget, ...] = ()
    run_count: int | None = None
    started_at: datetime | None = None


NO_IMPLEMENTATION_CONTEXT = ImplementationResearchContext()


class ReplacementOutputUnavailable(RuntimeError):
    pass


class ReplacementPullRequestUnverified(RuntimeError):
    pass


class TargetVerificationUnavailable(RuntimeError):
    """GitHub could not answer whether a target is still eligible, which is not the same as "no"."""


def _verify_replacement_prs(replacement: SignalReportArtefact, run_id: UUID, urls: list[str]) -> None:
    targets = {
        target.pr_url: target
        for target in automated_targets(replacement.team_id, str(replacement.report_id))
        if target.run_id == run_id and target.task_id == replacement.task_id
    }
    for url in urls:
        target = targets.get(url)
        if target is None or not verify_target(replacement.team_id, target, check_sha=False):
            raise ReplacementPullRequestUnverified("Could not verify an open PR created by the replacement run")


def _can_close_target(
    replacement: SignalReportArtefact,
    content: ImplementationReplacement,
    progress: ImplementationHandover,
    target: ImplementationTarget,
) -> bool:
    _verify_replacement_prs(replacement, content.run_id, progress.replacement_pr_urls)
    eligible = automated_targets(replacement.team_id, str(replacement.report_id))
    if not any(
        candidate.pr_url == target.pr_url
        and candidate.run_id == target.run_id
        and candidate.automation_artefact_id == target.automation_artefact_id
        for candidate in eligible
    ) or not verify_target(replacement.team_id, target):
        return False
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=replacement.team_id, id=replacement.report_id)
        claim = get_active_claim(team_id=replacement.team_id, report_id=replacement.report_id)
        reservation = latest_handover(replacement)
        return bool(
            reservation
            and reservation.worker_token == progress.worker_token
            and report.status == SignalReport.Status.READY
            and report.run_count == content.decision.research_run_count
            and report.last_run_at == content.decision.research_started_at
            and claim
            and claim.claim_id == replacement.claim_id
            and claim.actor_task_id == replacement.task_id
        )


def schedule_report_replacements(team_id: int, report_id: str) -> None:
    from products.signals.backend.tasks import reconcile_implementation_replacement

    replacement = pending_replacement(team_id, report_id)
    if replacement:
        transaction.on_commit(partial(reconcile_implementation_replacement.delay, team_id, str(replacement.id)))


def canonical_pr_url(url: str) -> str | None:
    parsed = GitHubIntegrationBase.parse_pull_request_url(url)
    return f"https://github.com/{parsed.repository.lower()}/pull/{parsed.number}" if parsed else None


def _automation_receipts(team_id: int, report_id: str) -> dict[UUID, SignalReportArtefact]:
    receipts: dict[UUID, SignalReportArtefact] = {}
    for row in SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="task_run"):
        try:
            content = TaskRunArtefact.model_validate_json(row.content)
            if (
                content.product == "signals"
                and content.type == "implementation"
                and content.automation_branch
                and content.run_id
                and row.actor_kind == "task"
                and str(row.task_id) == content.task_id
            ):
                receipts[UUID(content.run_id)] = row
        except (ValidationError, ValueError):
            continue
    return receipts


def automated_targets(team_id: int, report_id: str) -> list[ImplementationTarget]:
    task_ids = list(
        SignalReportTask.objects.filter(
            team_id=team_id, report_id=report_id, relationship="implementation"
        ).values_list("task_id", flat=True)
    )
    runs = tasks_facade.get_signal_report_implementation_runs(team_id, report_id, task_ids)
    active_tasks = {run.task_id for run in runs if not run.is_terminal}
    latest_runs: dict[UUID, UUID] = {}
    for run in runs:
        latest_runs.setdefault(run.task_id, run.id)
    receipts = _automation_receipts(team_id, report_id)
    prs = fetch_implementation_prs_for_reports([report_id], team_id=team_id).get(report_id, [])
    eligible_urls = {
        canonical_pr_url(pr.url)
        for pr in prs
        if pr.actor_kind in {"task", "system"} and pr.state not in {"closed", "merged"}
    }
    targets: dict[str, ImplementationTarget] = {}
    for run in runs:
        receipt = receipts.get(run.id)
        if (
            receipt is None
            or run.task_id in active_tasks
            or latest_runs[run.task_id] != run.id
            or run.status != "completed"
            or run.environment != "cloud"
            or run.mode != "background"
        ):
            continue
        content = TaskRunArtefact.model_validate_json(receipt.content)
        if (
            str(run.task_id) != content.task_id
            or run.state.get("ai_stage") != "implementation"
            or run.state.get("self_driving_head_branch") != content.automation_branch
        ):
            continue
        for raw_url in tasks_facade.read_pr_urls(run.output):
            url = canonical_pr_url(raw_url)
            if not url or url not in eligible_urls or url in targets:
                continue
            targets[url] = ImplementationTarget(
                task_id=run.task_id,
                run_id=run.id,
                claim_id=receipt.claim_id,
                pr_url=url,
                head_sha="unverified",
                automation_artefact_id=receipt.id,
            )
    return list(targets.values())


def verify_target(team_id: int, target: ImplementationTarget, *, check_sha: bool = True) -> str | None:
    receipt = SignalReportArtefact.objects.filter(
        team_id=team_id, id=target.automation_artefact_id, task_id=target.task_id, type="task_run"
    ).first()
    if receipt is None:
        return None
    content = TaskRunArtefact.model_validate_json(receipt.content)
    parsed = GitHubIntegrationBase.parse_pull_request_url(target.pr_url)
    if parsed is None or not content.automation_branch or content.run_id != str(target.run_id):
        return None
    tasks = tasks_facade.get_tasks_by_ids([target.task_id], [team_id])
    if not tasks or (tasks[0].repository or "").lower() != parsed.repository.lower():
        return None
    github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    if github is None:
        raise TargetVerificationUnavailable("GitHub integration unavailable")
    pr = github.get_pull_request(parsed.repository, parsed.number)
    if not pr.get("success"):
        raise TargetVerificationUnavailable("Could not verify pull request")
    sha = pr.get("head_sha")
    if (
        pr.get("state") != "open"
        or pr.get("merged")
        or not isinstance(sha, str)
        or not sha
        or pr.get("head_branch") != content.automation_branch
        or str(pr.get("head_repository", "")).lower() != parsed.repository.lower()
        or (check_sha and sha != target.head_sha)
    ):
        return None
    return sha


def research_implementation_context(team_id: int, report_id: str) -> ImplementationResearchContext:
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
    if report is None:
        return ImplementationResearchContext()
    try:
        candidates = []
        for target in automated_targets(team_id, report_id):
            sha = verify_target(team_id, target, check_sha=False)
            if sha:
                candidates.append(target.model_copy(update={"head_sha": sha}))
        return ImplementationResearchContext(
            candidates=tuple(candidates), run_count=report.run_count, started_at=report.last_run_at
        )
    except Exception:
        logger.exception("signals_automated_pr_lookup_failed", report_id=report_id)
        return ImplementationResearchContext()


def _target_already_closed(team_id: int, target: ImplementationTarget) -> bool:
    from products.signals.backend.report_assignments import update_assignments_for_pull_request

    parsed = GitHubIntegrationBase.parse_pull_request_url(target.pr_url)
    assert parsed is not None
    github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    current = github.get_pull_request(parsed.repository, parsed.number) if github else {}
    if not current.get("success"):
        raise RuntimeError("Could not verify predecessor state")
    closed = current.get("state") == "closed" and not current.get("merged")
    if closed:
        update_assignments_for_pull_request(
            team_ids=[team_id], repository=parsed.repository, pr_number=parsed.number, pr_state="closed"
        )
    return closed


def latest_handover(replacement: SignalReportArtefact) -> ImplementationHandover | None:
    if replacement.task_id is None:
        return None
    for row in SignalReportArtefact.objects.filter(
        team_id=replacement.team_id,
        report_id=replacement.report_id,
        task_id=replacement.task_id,
        type="implementation_handover",
    ).order_by("-created_at", "-id"):
        content = ImplementationHandover.model_validate_json(row.content)
        if content.replacement_id == replacement.id:
            return content
    return None


def pending_replacement(team_id: int, report_id: str) -> SignalReportArtefact | None:
    for row in SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type="implementation_replacement"
    ).order_by("-created_at", "-id"):
        if row.task_id is None:
            continue
        progress = latest_handover(row)
        if progress is None or progress.status == "processing":
            return row
    return None


def decision_is_current(report: SignalReport, decision: ImplementationDecision) -> bool:
    return bool(
        decision.supersede
        and decision.targets
        and decision.research_started_at
        and report.status == SignalReport.Status.READY
        and decision.research_run_count == report.run_count
        and decision.research_started_at == report.last_run_at
        and report.run_count > (report.implemented_at_run_count or 0)
        and pending_replacement(report.team_id, str(report.id)) is None
    )


def targets_still_eligible(report: SignalReport, decision: ImplementationDecision) -> bool:
    current = {
        (target.pr_url, target.run_id, target.automation_artefact_id)
        for target in automated_targets(report.team_id, str(report.id))
    }
    if any((target.pr_url, target.run_id, target.automation_artefact_id) not in current for target in decision.targets):
        return False
    claim = get_active_claim(team_id=report.team_id, report_id=report.id)
    return claim is None or (
        claim.actor_kind == "task"
        and any(
            claim.actor_task_id == target.task_id and claim.claim_id == target.claim_id for target in decision.targets
        )
    )


def append_handover(replacement: SignalReportArtefact, progress: ImplementationHandover) -> None:
    SignalReportArtefact.add_log(
        team_id=replacement.team_id,
        report_id=str(replacement.report_id),
        content=progress,
        attribution=ArtefactAttribution.from_task(str(replacement.task_id)),
        claim_id=str(replacement.claim_id) if replacement.claim_id else None,
    )


def _finish(replacement: SignalReportArtefact, progress: ImplementationHandover) -> None:
    from products.signals.backend.pull_requests import apply_report_completion
    from products.signals.backend.report_assignments import release_claim

    append_handover(replacement, progress)
    if progress.status in {"failed", "cancelled"}:
        claim = get_active_claim(team_id=replacement.team_id, report_id=replacement.report_id)
        if claim and claim.actor_task_id == replacement.task_id and claim.claim_id == replacement.claim_id:
            release_claim(claim, ArtefactAttribution.system())
    report = SignalReport.objects.get(team_id=replacement.team_id, id=replacement.report_id)
    apply_report_completion(report)


def reconcile_replacement(team_id: int, replacement_id: str) -> bool:
    """Return whether a bounded retry is needed. GitHub requests never hold the report lock."""
    replacement = SignalReportArtefact.objects.filter(
        team_id=team_id, id=replacement_id, type="implementation_replacement"
    ).first()
    if replacement is None or replacement.task_id is None:
        return False
    content = ImplementationReplacement.model_validate_json(replacement.content)
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=replacement.report_id)
        previous = latest_handover(replacement)
        if previous and previous.status != "processing":
            return False
        if previous and previous.lease_until and previous.lease_until > timezone.now():
            return True
        progress = ImplementationHandover(
            replacement_id=replacement.id,
            status="processing",
            attempt=(previous.attempt if previous else 0) + 1,
            results=previous.results if previous else {},
            replacement_pr_urls=previous.replacement_pr_urls if previous else [],
            worker_token=uuid4(),
            lease_until=timezone.now() + timedelta(seconds=HANDOVER_LEASE_SECONDS),
        )
        run = tasks_facade.get_task_run(content.run_id, team_id)
        claim = get_active_claim(team_id=team_id, report_id=report.id)
        if (
            report.status in {SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED, SignalReport.Status.RESOLVED}
            or not claim
            or claim.claim_id != replacement.claim_id
            or claim.actor_task_id != replacement.task_id
        ):
            _finish(
                replacement,
                progress.model_copy(
                    update={
                        "status": "cancelled",
                        "explanation": "Replacement stopped because report ownership or status changed.",
                    }
                ),
            )
            return False
        if run is None or (run.is_terminal and run.status != "completed"):
            _finish(
                replacement,
                progress.model_copy(
                    update={
                        "status": "failed",
                        "explanation": "The replacement run did not complete successfully. Existing PRs were left open.",
                    }
                ),
            )
            return False
        if not run.is_terminal:
            return False
        if report.run_count != content.decision.research_run_count or report.status != SignalReport.Status.READY:
            _finish(
                replacement,
                progress.model_copy(
                    update={
                        "status": "needs_attention",
                        "explanation": "Research changed while the replacement was running. Review the PRs before closing earlier work.",
                    }
                ),
            )
            return False
        if progress.attempt > MAX_HANDOVER_ATTEMPTS:
            _finish(
                replacement,
                progress.model_copy(
                    update={
                        "status": "needs_attention",
                        "explanation": "Automatic handover could not finish. Review the linked PRs.",
                    }
                ),
            )
            return False
        append_handover(replacement, progress)
        from products.signals.backend.tasks import reconcile_implementation_replacement

        # A delayed wake-up survives a worker dying after it reserves the handover.
        transaction.on_commit(
            partial(
                reconcile_implementation_replacement.apply_async,
                args=(team_id, replacement_id),
                countdown=HANDOVER_LEASE_SECONDS + 1,
            )
        )
    retry = False
    try:
        replacement_urls = [url for raw in tasks_facade.read_pr_urls(run.output) if (url := canonical_pr_url(raw))]
        prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=team_id).get(str(report.id), [])
        linked = {canonical_pr_url(pr.url): pr for pr in prs}
        if not replacement_urls or any(
            url not in linked or linked[url].task_id != str(replacement.task_id) for url in replacement_urls
        ):
            raise ReplacementOutputUnavailable("Replacement PR links are not available")
        _verify_replacement_prs(replacement, content.run_id, replacement_urls)
        progress.replacement_pr_urls = replacement_urls
        eligible = {target.pr_url: target for target in automated_targets(team_id, str(report.id))}
        for target in content.decision.targets:
            if target.pr_url in progress.results:
                continue
            if target.pr_url in replacement_urls or target.pr_url not in linked:
                progress.results[target.pr_url] = "skipped"
                continue
            pr = linked[target.pr_url]
            if _target_already_closed(team_id, target):
                progress.results[target.pr_url] = "already_closed"
                continue
            candidate = eligible.get(target.pr_url)
            if (
                not candidate
                or candidate.run_id != target.run_id
                or candidate.automation_artefact_id != target.automation_artefact_id
                or not verify_target(team_id, target)
            ):
                progress.results[target.pr_url] = "skipped"
                continue
            if implementation_pr_needed_by_another_report(
                team_id=team_id, report_id=str(report.id), pr_url=target.pr_url
            ):
                # The close path refuses a PR another unfinished report still needs, and no attempt
                # can change that while the other report runs, so record the outcome here instead of
                # spending the attempt budget on a decision that cannot move.
                progress.results[target.pr_url] = "skipped"
                continue
            with transaction.atomic():
                current_report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report.id)
                current_claim = get_active_claim(team_id=team_id, report_id=report.id)
                reservation = latest_handover(replacement)
                if not reservation or reservation.worker_token != progress.worker_token:
                    return False
                if (
                    current_report.status != SignalReport.Status.READY
                    or current_report.run_count != content.decision.research_run_count
                    or not current_claim
                    or current_claim.claim_id != replacement.claim_id
                ):
                    progress.status = "cancelled"
                    progress.explanation = (
                        "Handover stopped because report ownership or research changed. Review the remaining PRs."
                    )
                    progress.lease_until = None
                    _finish(replacement, progress)
                    return False
            if _close_implementation_pr(
                team_id,
                str(report.id),
                reason="superseded",
                pr=pr,
                replacement_pr_url=", ".join(replacement_urls),
                expected_head_sha=target.head_sha,
                comment_marker=f"<!-- signals-replacement:{replacement.id} -->",
                before_close=partial(_can_close_target, replacement, content, progress, target),
            ):
                progress.results[target.pr_url] = "closed"
            else:
                raise RuntimeError("Could not close an obsolete PR")
            with transaction.atomic():
                SignalReport.objects.select_for_update().get(team_id=team_id, id=report.id)
                reservation = latest_handover(replacement)
                if not reservation or reservation.worker_token != progress.worker_token:
                    return False
                append_handover(replacement, progress)
        progress.status = "needs_attention" if "skipped" in progress.results.values() else "completed"
        progress.explanation = (
            "Review the PRs left open."
            if progress.status == "needs_attention"
            else "The replacement finished and the selected obsolete PRs are closed."
        )
    except ReplacementPullRequestUnverified:
        progress.status = "needs_attention"
        progress.explanation = (
            "Could not verify an open PR created by the replacement run. Review the earlier PRs still open."
        )
    except Exception as error:
        logger.exception("signals_replacement_handover_failed", replacement_id=replacement_id)
        retry = progress.attempt < MAX_HANDOVER_ATTEMPTS
        progress.status = (
            "processing"
            if retry
            else "failed"
            if isinstance(error, ReplacementOutputUnavailable)
            else "needs_attention"
        )
        progress.explanation = "Could not finish the handover. Review the PRs still open."
    with transaction.atomic():
        SignalReport.objects.select_for_update().get(team_id=team_id, id=report.id)
        reservation = latest_handover(replacement)
        if reservation and reservation.worker_token == progress.worker_token:
            progress.lease_until = None
            if progress.status == "processing":
                append_handover(replacement, progress)
            else:
                _finish(replacement, progress)
    return retry
