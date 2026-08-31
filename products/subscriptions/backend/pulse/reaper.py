"""Bounded convergence for stranded Pulse orchestration state."""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal, NamedTuple
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

from products.experiments.backend.facade import api as experiments_facade
from products.subscriptions.backend.facade.pulse import purge_expired_evidence_raw_bodies
from products.subscriptions.backend.models import Artifact, OutcomePlan, PulseRun, RunAction
from products.tasks.backend.facade import (
    api as tasks_facade,
    contracts as tasks_contracts,
)

from .contracts import PulseReaperResult
from .orchestration import (
    _ACTIVE_RUN_STATUSES,
    _TERMINAL_RUN_STATUSES,
    bind_pulse_analysis_task,
    bind_pulse_execution_task,
    reconcile_pulse_draft_publication,
    reconcile_pulse_task_terminal_state,
    request_pulse_run_cancellation,
)
from .outcomes import abandon_outcome_plan, adopt_outcome_plan, mark_due_or_release_expired_outcome_plan

logger = structlog.get_logger(__name__)

PULSE_REAPER_BATCH_SIZE = 100
PULSE_REAPER_MISSING_TASK_GRACE = timedelta(minutes=10)


class _ArtifactOutcomeState(NamedTuple):
    state: Literal["pending", "adopted", "abandoned"]
    source: str | None = None
    changed_at: datetime | None = None
    reason: str | None = None


@frozen
class _PulseRunReconciliationCandidate:
    team_id: int
    run_id: UUID
    task_id: UUID | None
    analysis_task_run_id: UUID | None
    execution_task_run_id: UUID | None
    finalization_deadline_at: datetime | None
    cancellation_requested_at: datetime | None


@frozen
class _UnknownDraftArtifactCandidate:
    team_id: int
    artifact_id: UUID
    run_id: UUID
    task_id: UUID
    analysis_task_run_id: UUID
    execution_task_run_id: UUID
    publication_lease_id: UUID


def _candidate_runs(*, batch_size: int) -> list[_PulseRunReconciliationCandidate]:
    candidates = list(PulseRun.all_teams.filter(status__in=_ACTIVE_RUN_STATUSES).order_by("updated_at")[:batch_size])
    return [
        _PulseRunReconciliationCandidate(
            team_id=run.team_id,
            run_id=run.id,
            task_id=run.task_id,
            analysis_task_run_id=run.analysis_task_run_id,
            execution_task_run_id=run.execution_task_run_id,
            finalization_deadline_at=run.finalization_deadline_at,
            cancellation_requested_at=run.cancellation_requested_at,
        )
        for run in candidates
    ]


def _candidate_unknown_artifacts(*, batch_size: int) -> list[_UnknownDraftArtifactCandidate]:
    artifacts = (
        Artifact.all_teams.select_related("run")
        .filter(
            status=Artifact.Status.PUBLICATION_UNKNOWN,
            kind=Artifact.Kind.DRAFT_PR,
            run__status__in=_TERMINAL_RUN_STATUSES,
            task_id__isnull=False,
            execution_task_run_id__isnull=False,
            publication_lease_id__isnull=False,
            run__analysis_task_run_id__isnull=False,
        )
        .order_by("updated_at")[:batch_size]
    )
    return [
        _UnknownDraftArtifactCandidate(
            team_id=artifact.team_id,
            artifact_id=artifact.id,
            run_id=artifact.run_id,
            task_id=artifact.task_id,
            analysis_task_run_id=artifact.run.analysis_task_run_id,
            execution_task_run_id=artifact.execution_task_run_id,
            publication_lease_id=artifact.publication_lease_id,
        )
        for artifact in artifacts
        if (
            artifact.task_id is not None
            and artifact.run.analysis_task_run_id is not None
            and artifact.execution_task_run_id is not None
            and artifact.publication_lease_id is not None
        )
    ]


def reconcile_pulse_runs(
    *, now: datetime | None = None, batch_size: int = PULSE_REAPER_BATCH_SIZE
) -> PulseReaperResult:
    """Reconcile only caller-bound Task runs, then purge expired encrypted evidence."""
    if batch_size < 1 or batch_size > PULSE_REAPER_BATCH_SIZE:
        raise ValueError("Pulse reaper batch size is invalid.")
    current_time = now or timezone.now()
    reconciled = 0
    active_batch_size = max(1, batch_size // 2)
    for candidate in _candidate_runs(batch_size=active_batch_size):
        try:
            if candidate.task_id is None or candidate.analysis_task_run_id is None:
                discovered = tasks_facade.get_staged_task_by_idempotency(
                    tasks_contracts.GetStagedTaskByIdempotencyInput(
                        team_id=candidate.team_id,
                        caller_id=candidate.run_id,
                        idempotency_key=f"pulse:{candidate.run_id}:analysis",
                    )
                )
                if discovered is None:
                    if (
                        candidate.finalization_deadline_at is not None
                        and current_time >= candidate.finalization_deadline_at
                    ):
                        if _terminalize_unbound_run(
                            team_id=candidate.team_id,
                            run_id=candidate.run_id,
                            now=current_time,
                        ):
                            reconciled += 1
                    continue
                bind_pulse_analysis_task(
                    team_id=candidate.team_id,
                    run_id=candidate.run_id,
                    task_id=discovered.task_id,
                    analysis_task_run_id=discovered.analysis_run_id,
                    reconcile_existing=True,
                )
                candidate = replace(
                    candidate,
                    task_id=discovered.task_id,
                    analysis_task_run_id=discovered.analysis_run_id,
                )
            assert candidate.task_id is not None
            assert candidate.analysis_task_run_id is not None
            if candidate.execution_task_run_id is None:
                selected = (
                    RunAction.objects.for_team(candidate.team_id)
                    .filter(run_id=candidate.run_id, implementation_selected=True)
                    .only("action_key")
                    .first()
                )
                if selected is not None:
                    discovered_execution = tasks_facade.get_staged_execution_by_idempotency(
                        tasks_contracts.GetStagedExecutionByIdempotencyInput(
                            team_id=candidate.team_id,
                            caller_id=candidate.run_id,
                            task_id=candidate.task_id,
                            source_run_id=candidate.analysis_task_run_id,
                            idempotency_key=f"pulse:{candidate.run_id}:{selected.action_key}:execution",
                        )
                    )
                    if discovered_execution is not None:
                        bind_pulse_execution_task(
                            team_id=candidate.team_id,
                            run_id=candidate.run_id,
                            task_id=discovered_execution.task_id,
                            analysis_task_run_id=discovered_execution.analysis_run_id,
                            execution_task_run_id=discovered_execution.execution_run_id,
                            publication_lease_id=discovered_execution.publication_lease_id,
                            reconcile_existing=True,
                        )
                        candidate = replace(
                            candidate,
                            execution_task_run_id=discovered_execution.execution_run_id,
                        )
            if (
                candidate.finalization_deadline_at is not None
                and current_time >= candidate.finalization_deadline_at
                and candidate.cancellation_requested_at is None
            ):
                request_pulse_run_cancellation(
                    team_id=candidate.team_id,
                    run_id=candidate.run_id,
                    now=current_time,
                )
                candidate = replace(candidate, cancellation_requested_at=current_time)
            assert candidate.task_id is not None
            assert candidate.analysis_task_run_id is not None
            task_run_id = candidate.execution_task_run_id or candidate.analysis_task_run_id
            assert task_run_id is not None
            task_run = tasks_facade.get_task_run(task_run_id, team_id=candidate.team_id)
            if task_run is None or task_run.task_id != candidate.task_id:
                if (
                    candidate.cancellation_requested_at is not None
                    and current_time >= candidate.cancellation_requested_at + PULSE_REAPER_MISSING_TASK_GRACE
                ):
                    reconcile_pulse_task_terminal_state(
                        team_id=candidate.team_id,
                        run_id=candidate.run_id,
                        task_run_id=task_run_id,
                        task_status="cancelled",
                        now=current_time,
                        failure_code="task_missing_after_cancellation",
                    )
                    reconciled += 1
                continue
            if candidate.cancellation_requested_at is not None:
                tasks_facade.cancel_staged_task(
                    tasks_contracts.CancelStagedTaskInput(
                        team_id=candidate.team_id,
                        caller_id=candidate.run_id,
                        task_id=candidate.task_id,
                        source_run_id=candidate.analysis_task_run_id,
                    )
                )
            if not task_run.is_terminal:
                continue
            if (
                candidate.execution_task_run_id is None
                and task_run.status == "completed"
                and candidate.cancellation_requested_at is None
            ):
                continue
            if candidate.execution_task_run_id is not None:
                reconcile_pulse_draft_publication(
                    team_id=candidate.team_id,
                    run_id=candidate.run_id,
                    now=current_time,
                )
            reconciled_run = reconcile_pulse_task_terminal_state(
                team_id=candidate.team_id,
                run_id=candidate.run_id,
                task_run_id=task_run_id,
                task_status=task_run.status,
                now=current_time,
            )
            if reconciled_run.status in _TERMINAL_RUN_STATUSES:
                reconciled += 1
        except Exception as error:
            capture_exception(error)
            logger.exception(
                "pulse_reaper.run_reconcile_failed",
                team_id=candidate.team_id,
                run_id=str(candidate.run_id),
            )
        finally:
            PulseRun.objects.for_team(candidate.team_id).filter(
                id=candidate.run_id,
                status__in=_ACTIVE_RUN_STATUSES,
            ).update(updated_at=current_time)
    for artifact_candidate in _candidate_unknown_artifacts(batch_size=batch_size - active_batch_size):
        try:
            if _reconcile_unknown_draft_artifact(
                team_id=artifact_candidate.team_id,
                artifact_id=artifact_candidate.artifact_id,
                run_id=artifact_candidate.run_id,
                task_id=artifact_candidate.task_id,
                analysis_task_run_id=artifact_candidate.analysis_task_run_id,
                execution_task_run_id=artifact_candidate.execution_task_run_id,
                publication_lease_id=artifact_candidate.publication_lease_id,
            ):
                reconciled += 1
        except Exception as error:
            capture_exception(error)
            logger.exception(
                "pulse_reaper.artifact_reconcile_failed",
                team_id=artifact_candidate.team_id,
                artifact_id=str(artifact_candidate.artifact_id),
            )
    purged = purge_expired_evidence_raw_bodies(now=current_time)
    reconciled += _reconcile_outcome_plans(now=current_time, batch_size=batch_size)
    return PulseReaperResult(reconciled_count=reconciled, purged_evidence_count=purged)


def _reconcile_outcome_plans(*, now: datetime, batch_size: int) -> int:
    """Converge only exact prepared artifact lifecycle state in a bounded reaper batch."""
    if not getattr(settings, "PULSE_PROACTIVE_ENABLED", False) or not getattr(
        settings, "PULSE_OUTCOME_READOUT_ENABLED", False
    ):
        return 0
    expiry_seconds = _outcome_claim_expiry_seconds()
    expiry = now - timedelta(seconds=expiry_seconds)
    lifecycle_limit = max(1, batch_size // 4)
    urgent_limit = batch_size - lifecycle_limit
    expired_limit = max(1, urgent_limit // 4) if urgent_limit else 0
    scheduled_limit = urgent_limit - expired_limit
    scheduled = list(
        OutcomePlan.all_teams.filter(readout_status=OutcomePlan.ReadoutStatus.SCHEDULED, next_readout_at__lte=now)
        .order_by("next_readout_at")
        .values_list("team_id", "id", "source_action_id")[:scheduled_limit]
    )
    expired = list(
        OutcomePlan.all_teams.filter(
            Q(claimed_at__lte=expiry) | Q(claimed_at__isnull=True),
            readout_status=OutcomePlan.ReadoutStatus.MEASURING,
        )
        .order_by("claimed_at")
        .values_list("team_id", "id", "source_action_id")[:expired_limit]
    )
    pending_qs = OutcomePlan.all_teams.filter(
        adoption_status=OutcomePlan.AdoptionStatus.PENDING,
        readout_status=OutcomePlan.ReadoutStatus.WAITING,
    ).order_by("updated_at", "id")
    pending = list(pending_qs.values_list("team_id", "id", "source_action_id")[:lifecycle_limit])
    pending_plan_ids = {(team_id, plan_id) for team_id, plan_id, _ in pending}
    plans = [*scheduled, *expired, *pending]
    changed = 0
    for team_id, plan_id, source_action_id in plans:
        try:
            plan = (
                OutcomePlan.objects.for_team(team_id)
                .select_related("source_action")
                .filter(id=plan_id, source_action_id=source_action_id)
                .first()
            )
            if plan is None:
                continue
            artifacts = list(
                Artifact.objects.for_team(team_id)
                .select_related("run")
                .filter(action_id=source_action_id, status=Artifact.Status.VERIFIED)
                .order_by("kind", "created_at")
            )
            if _reconcile_outcome_artifacts(team_id=team_id, plan=plan, artifacts=artifacts, now=now):
                changed += 1
                continue
            if (team_id, plan_id) in pending_plan_ids:
                OutcomePlan.objects.for_team(team_id).filter(id=plan_id).update(updated_at=now)
            if mark_due_or_release_expired_outcome_plan(team_id=team_id, plan_id=plan_id, now=now):
                changed += 1
        except Exception as error:
            capture_exception(error)
            logger.exception("pulse_reaper.outcome_reconcile_failed", team_id=team_id, plan_id=str(plan_id))
    return changed


def _outcome_claim_expiry_seconds() -> int:
    value = getattr(settings, "PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS", 7200)
    return min(value, 24 * 60 * 60) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 7200


def _reconcile_outcome_artifacts(*, team_id: int, plan: OutcomePlan, artifacts: list[Artifact], now: datetime) -> bool:
    expected_kinds = (
        {Artifact.Kind.DRAFT_PR, Artifact.Kind.EXPERIMENT_DRAFT}
        if plan.source_action.kind == RunAction.Kind.COMBINED
        else {plan.source_action.kind}
    )
    artifacts_by_kind = {artifact.kind: artifact for artifact in artifacts if artifact.kind in expected_kinds}
    if set(artifacts_by_kind) != expected_kinds:
        return False
    states = [
        _outcome_artifact_state(team_id=team_id, artifact=artifacts_by_kind[kind]) for kind in sorted(expected_kinds)
    ]
    abandoned = next((state for state in states if state.state == "abandoned"), None)
    if abandoned is not None:
        return abandon_outcome_plan(
            team_id=team_id,
            plan_id=plan.id,
            now=now,
            reason=abandoned.reason or "artifact_abandoned",
        )
    if any(state.state != "adopted" for state in states):
        return False
    adopted = max(
        states,
        key=lambda state: (
            state.changed_at or datetime.min.replace(tzinfo=now.tzinfo),
            state.source == OutcomePlan.AdoptionSource.EXPERIMENT_LAUNCHED,
        ),
    )
    if adopted.source is None or adopted.changed_at is None:
        return False
    return adopt_outcome_plan(
        team_id=team_id,
        plan_id=plan.id,
        source=adopted.source,
        adopted_at=adopted.changed_at,
        now=now,
    )


def _outcome_artifact_state(*, team_id: int, artifact: Artifact) -> _ArtifactOutcomeState:
    if artifact.kind == Artifact.Kind.DRAFT_PR:
        if (
            artifact.task_id is None
            or artifact.run.analysis_task_run_id is None
            or artifact.execution_task_run_id is None
            or artifact.publication_lease_id is None
        ):
            return _ArtifactOutcomeState("pending")
        lifecycle = tasks_facade.get_staged_artifact_lifecycle(
            tasks_contracts.GetStagedArtifactLifecycleInput(
                team_id=team_id,
                caller_id=artifact.run_id,
                task_id=artifact.task_id,
                source_run_id=artifact.run.analysis_task_run_id,
                execution_run_id=artifact.execution_task_run_id,
                publication_lease_id=artifact.publication_lease_id,
            )
        )
        if lifecycle is None or lifecycle.state in {"unknown", "open"}:
            return _ArtifactOutcomeState("pending")
        if lifecycle.state == "merged" and lifecycle.changed_at is not None:
            return _ArtifactOutcomeState(
                "adopted",
                source=OutcomePlan.AdoptionSource.PULL_REQUEST_MERGED,
                changed_at=lifecycle.changed_at,
            )
        return _ArtifactOutcomeState("abandoned", reason="pull_request_closed")
    if artifact.kind == Artifact.Kind.EXPERIMENT_DRAFT and artifact.experiment_id is not None:
        experiment_lifecycle = experiments_facade.get_pulse_experiment_lifecycle(
            team_id=team_id, experiment_id=artifact.experiment_id
        )
        if experiment_lifecycle is None or experiment_lifecycle.state == "draft":
            return _ArtifactOutcomeState("pending")
        if experiment_lifecycle.state == "deleted":
            return _ArtifactOutcomeState("abandoned", reason="experiment_deleted")
        if experiment_lifecycle.launched_at is None:
            return _ArtifactOutcomeState("pending")
        return _ArtifactOutcomeState(
            "adopted",
            source=OutcomePlan.AdoptionSource.EXPERIMENT_LAUNCHED,
            changed_at=experiment_lifecycle.launched_at,
        )
    return _ArtifactOutcomeState("pending")


def _terminalize_unbound_run(*, team_id: int, run_id: UUID, now: datetime) -> bool:
    """Close a deadline-expired run that crashed before it gained a Tasks identity."""
    with transaction.atomic():
        run = PulseRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        if (
            run.status not in _ACTIVE_RUN_STATUSES
            or run.task_id is not None
            or run.analysis_task_run_id is not None
            or run.finalization_deadline_at is None
            or now < run.finalization_deadline_at
        ):
            return False
        run.cancellation_requested_at = run.cancellation_requested_at or now
        run.status = PulseRun.Status.CANCELLED
        run.failure_code = "finalization_timeout"
        run.finished_at = now
        run.save(update_fields=["cancellation_requested_at", "status", "failure_code", "finished_at", "updated_at"])
        return True


def _reconcile_unknown_draft_artifact(
    *,
    team_id: int,
    artifact_id: UUID,
    run_id: UUID,
    task_id: UUID,
    analysis_task_run_id: UUID,
    execution_task_run_id: UUID,
    publication_lease_id: UUID,
) -> bool:
    """Resolve only a caller-bound publication; absent or intermediate state remains unknown."""
    publication = tasks_facade.get_staged_draft_publication(
        tasks_contracts.GetStagedDraftPublicationInput(
            team_id=team_id,
            caller_id=run_id,
            task_id=task_id,
            source_run_id=analysis_task_run_id,
            execution_run_id=execution_task_run_id,
            publication_lease_id=publication_lease_id,
        )
    )
    if publication is None or publication.status not in {"finalized", "blocked", "revoked"}:
        return False
    with transaction.atomic():
        run = PulseRun.objects.for_team(team_id).select_for_update().filter(id=run_id).first()
        if (
            run is None
            or run.status not in _TERMINAL_RUN_STATUSES
            or run.task_id != task_id
            or run.analysis_task_run_id != analysis_task_run_id
            or run.execution_task_run_id != execution_task_run_id
        ):
            return False
        artifact = Artifact.objects.for_team(team_id).select_for_update().filter(id=artifact_id, run_id=run_id).first()
        if artifact is None or artifact.status != Artifact.Status.PUBLICATION_UNKNOWN:
            return False
        if publication.status == "finalized" and publication.pr_number is not None and publication.pr_url:
            artifact.status = Artifact.Status.VERIFIED
            artifact.external_id = str(publication.pr_number)
            artifact.external_url = publication.pr_url
            artifact.verified_at = timezone.now()
            artifact.failure_code = None
            artifact.save(
                update_fields=[
                    "status",
                    "external_id",
                    "external_url",
                    "verified_at",
                    "failure_code",
                    "updated_at",
                ]
            )
            return True
        if publication.status in {"blocked", "revoked"}:
            artifact.status = Artifact.Status.FAILED
            artifact.failure_code = f"publication_{publication.status}"
            artifact.active_claim = False
            artifact.save(update_fields=["status", "failure_code", "active_claim", "updated_at"])
            return True
    return False


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def reconcile_pulse_runs_task() -> None:
    result = reconcile_pulse_runs()
    logger.info(
        "pulse_reaper.swept",
        reconciled_count=result.reconciled_count,
        purged_evidence_count=result.purged_evidence_count,
    )
