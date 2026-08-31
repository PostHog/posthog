"""Durable, subscription-owned orchestration state for proactive Pulse runs."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone

from posthog.models import Team

from products.subscriptions.backend.models import (
    ActionProposal,
    Artifact,
    EvidenceSet,
    EvidenceToolCall,
    Opportunity,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.tasks.backend.facade import (
    api as tasks_facade,
    contracts as tasks_contracts,
)

from .contracts import (
    MeasurementCandidate,
    PulseAnalysisActionInput,
    PulseAnalysisPersistenceDTO,
    PulseAnalysisPersistenceInput,
    PulseOutcomeReadoutPersistenceInput,
    PulseRunCreationInput,
)
from .measurements import MeasurementValidationError, canonicalize_measurement, measurement_identity
from .outcomes import PulseOutcomeConflict, create_outcome_plan, load_measurement_evidence, persist_outcome_readouts
from .services import stable_action_key
from .telemetry import capture_pulse_outcome, capture_pulse_run_started, capture_pulse_run_terminalized

MAX_PULSE_ACTIONS = 3
MAX_PULSE_TOOL_CALLS = 20
MAX_PULSE_PUBLIC_RESEARCH_CALLS = 3
MAX_PULSE_RUNTIME_SECONDS = 60 * 60
MAX_PULSE_ACTION_TARGET_ENTRIES = 32
MAX_PULSE_ACTION_SELECTOR_ENTRIES = 32
_SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS = frozenset({200_000, 1_000_000})
MAX_FINALIZATION_MARGIN = timedelta(minutes=15)
MAX_TEAM_CONCURRENT_RUNS = 10
MAX_GLOBAL_CONCURRENT_RUNS = 100
MAX_TEAM_DAILY_RUNS = 100
MAX_GLOBAL_DAILY_RUNS = 1_000
_PULSE_GLOBAL_LIMIT_LOCK = 7_392_061

_KILL_SWITCHES = frozenset(
    {"allow_draft_pr", "allow_experiment_draft", "allow_public_research", "allow_outcome_readouts"}
)
_TERMINAL_RUN_STATUSES = frozenset(
    {
        PulseRun.Status.COMPLETED,
        PulseRun.Status.PARTIAL,
        PulseRun.Status.FAILED,
        PulseRun.Status.CANCELLED,
        PulseRun.Status.SKIPPED,
    }
)
_ACTIVE_RUN_STATUSES = frozenset(
    {
        PulseRun.Status.PENDING,
        PulseRun.Status.ANALYZING,
        PulseRun.Status.RESERVING,
        PulseRun.Status.EXECUTING,
    }
)
_TASK_FAILED_STATUSES = frozenset({"failed", "cancelled"})


class PulseOrchestrationConflict(ValueError):
    pass


def _bounded_setting(name: str, *, default: int, cap: int) -> int:
    value = getattr(settings, name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return min(value, cap)


def _effective_flags(raw_flags: dict[str, object]) -> dict[str, bool]:
    global_enabled = bool(getattr(settings, "PULSE_PROACTIVE_ENABLED", False))
    return {
        "allow_draft_pr": global_enabled
        and raw_flags.get("allow_draft_pr") is True
        and bool(getattr(settings, "PULSE_DRAFT_PR_ENABLED", False)),
        "allow_experiment_draft": global_enabled
        and raw_flags.get("allow_experiment_draft") is True
        and bool(getattr(settings, "PULSE_EXPERIMENT_DRAFT_ENABLED", False)),
        "allow_public_research": global_enabled
        and raw_flags.get("allow_public_research") is True
        and bool(getattr(settings, "PULSE_PUBLIC_RESEARCH_ENABLED", False)),
        "allow_outcome_readouts": global_enabled
        and raw_flags.get("allow_outcome_readouts") is True
        and bool(getattr(settings, "PULSE_OUTCOME_READOUT_ENABLED", False)),
    }


def _finalization_deadline(input: PulseRunCreationInput) -> datetime | None:
    if input.wall_clock_deadline_at is None:
        return None
    if input.wall_clock_deadline_at.tzinfo is None:
        raise PulseOrchestrationConflict("Pulse wall-clock deadline must include a timezone.")
    margin_seconds = input.finalization_margin_seconds
    if (
        not isinstance(margin_seconds, int)
        or isinstance(margin_seconds, bool)
        or not 0 < margin_seconds <= int(MAX_FINALIZATION_MARGIN.total_seconds())
    ):
        raise PulseOrchestrationConflict("Pulse finalization margin is invalid.")
    cutoff = input.wall_clock_deadline_at - timedelta(seconds=margin_seconds)
    if cutoff <= timezone.now():
        raise PulseOrchestrationConflict("Pulse finalization deadline is already elapsed.")
    return cutoff


def _json_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    """Validate, bound, and clone the immutable server-produced config snapshot."""
    try:
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        copied = json.loads(serialized)
    except (TypeError, ValueError) as error:
        raise PulseOrchestrationConflict("Pulse snapshot must be JSON serializable.") from error
    if not isinstance(copied, dict):
        raise PulseOrchestrationConflict("Pulse snapshot must be an object.")

    raw_flags = copied.get("flags", {})
    if not isinstance(raw_flags, dict) or set(raw_flags) - _KILL_SWITCHES:
        raise PulseOrchestrationConflict("Pulse snapshot flags are invalid.")
    if any(not isinstance(value, bool) for value in raw_flags.values()):
        raise PulseOrchestrationConflict("Pulse snapshot flags are invalid.")
    copied["flags"] = _effective_flags(raw_flags)

    raw_limits = copied.get("limits", {})
    allowed_limits = {
        "max_actions",
        "max_tool_calls",
        "max_public_research_calls",
        "max_runtime_seconds",
        "max_agent_context_tokens",
        "max_due_readouts",
        "outcome_memory_max_rows",
        "outcome_memory_max_bytes",
    }
    if not isinstance(raw_limits, dict) or set(raw_limits) - allowed_limits:
        raise PulseOrchestrationConflict("Pulse snapshot limits are invalid.")
    limit_caps = {
        "max_actions": MAX_PULSE_ACTIONS,
        "max_tool_calls": MAX_PULSE_TOOL_CALLS,
        "max_public_research_calls": MAX_PULSE_PUBLIC_RESEARCH_CALLS,
        "max_runtime_seconds": MAX_PULSE_RUNTIME_SECONDS,
        "max_due_readouts": 10,
        "outcome_memory_max_rows": 100,
        "outcome_memory_max_bytes": 32 * 1024,
    }
    limits: dict[str, int] = {}
    for key, cap in limit_caps.items():
        value = raw_limits.get(key, cap)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > cap:
            raise PulseOrchestrationConflict("Pulse snapshot limits exceed hard caps.")
        limits[key] = value
    context_window_tokens = raw_limits.get("max_agent_context_tokens", 200_000)
    if type(context_window_tokens) is not int or context_window_tokens not in _SUPPORTED_AGENT_CONTEXT_WINDOW_TOKENS:
        raise PulseOrchestrationConflict("Pulse snapshot agent context window is invalid.")
    limits["max_agent_context_tokens"] = context_window_tokens
    copied["limits"] = limits
    return copied


def _snapshots_match(
    run: PulseRun,
    input: PulseRunCreationInput,
    snapshot: dict[str, object],
    finalization_deadline_at: datetime | None,
) -> bool:
    return (
        run.subscription_id == input.subscription_id
        and run.report_snapshot_ref == input.report_snapshot_ref
        and run.config_snapshot == snapshot
        and run.wall_clock_deadline_at == input.wall_clock_deadline_at
        and run.finalization_deadline_at == finalization_deadline_at
    )


def create_or_reconcile_pulse_run(input: PulseRunCreationInput) -> PulseRun:
    """Create exactly one run for a delivery, recording overlap as a durable skip."""
    snapshot = _json_snapshot(input.config_snapshot)
    finalization_deadline_at = _finalization_deadline(input)
    with transaction.atomic():
        Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_PULSE_GLOBAL_LIMIT_LOCK])
        existing = (
            PulseRun.objects.for_team(input.team_id).select_for_update().filter(delivery_id=input.delivery_id).first()
        )
        if existing is not None:
            if not _snapshots_match(existing, input, snapshot, finalization_deadline_at):
                raise PulseOrchestrationConflict("Pulse delivery retry does not match its original snapshot.")
            return existing

        current_time = timezone.now()
        active = (
            PulseRun.objects.for_team(input.team_id)
            .select_for_update()
            .filter(subscription_id=input.subscription_id, status__in=_ACTIVE_RUN_STATUSES)
            .exists()
        )
        team_active_count = PulseRun.objects.for_team(input.team_id).filter(status__in=_ACTIVE_RUN_STATUSES).count()
        global_active_count = PulseRun.all_teams.filter(status__in=_ACTIVE_RUN_STATUSES).count()
        day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        team_daily_count = (
            PulseRun.objects.for_team(input.team_id)
            .filter(created_at__gte=day_start)
            .exclude(status=PulseRun.Status.SKIPPED)
            .count()
        )
        global_daily_count = (
            PulseRun.all_teams.filter(created_at__gte=day_start).exclude(status=PulseRun.Status.SKIPPED).count()
        )
        skip_reason: str | None = None
        if not getattr(settings, "PULSE_PROACTIVE_ENABLED", False):
            skip_reason = "proactive_disabled"
        elif active:
            skip_reason = "overlap_active_run"
        elif team_active_count >= _bounded_setting(
            "PULSE_MAX_TEAM_CONCURRENT_RUNS", default=1, cap=MAX_TEAM_CONCURRENT_RUNS
        ):
            skip_reason = "team_concurrency_limit"
        elif global_active_count >= _bounded_setting(
            "PULSE_MAX_GLOBAL_CONCURRENT_RUNS", default=10, cap=MAX_GLOBAL_CONCURRENT_RUNS
        ):
            skip_reason = "global_concurrency_limit"
        elif team_daily_count >= _bounded_setting("PULSE_MAX_TEAM_DAILY_RUNS", default=24, cap=MAX_TEAM_DAILY_RUNS):
            skip_reason = "team_daily_limit"
        elif global_daily_count >= _bounded_setting(
            "PULSE_MAX_GLOBAL_DAILY_RUNS", default=100, cap=MAX_GLOBAL_DAILY_RUNS
        ):
            skip_reason = "global_daily_limit"
        defaults: dict[str, object] = {
            "team_id": input.team_id,
            "subscription_id": input.subscription_id,
            "delivery_id": input.delivery_id,
            "report_snapshot_ref": input.report_snapshot_ref,
            "config_snapshot": snapshot,
            "wall_clock_deadline_at": input.wall_clock_deadline_at,
            "finalization_deadline_at": finalization_deadline_at,
        }
        if skip_reason is not None:
            defaults.update(
                {
                    "status": PulseRun.Status.SKIPPED,
                    "skip_reason": skip_reason,
                    "failure_code": skip_reason,
                    "finished_at": current_time,
                }
            )
        try:
            return PulseRun.objects.for_team(input.team_id).create(**defaults)
        except IntegrityError:
            existing = (
                PulseRun.objects.for_team(input.team_id)
                .select_for_update()
                .filter(delivery_id=input.delivery_id)
                .first()
            )
            if existing is not None and _snapshots_match(existing, input, snapshot, finalization_deadline_at):
                return existing
            raise PulseOrchestrationConflict("Pulse delivery could not be created safely.")


def _get_locked_run(*, team_id: int, run_id: UUID) -> PulseRun:
    try:
        return PulseRun.objects.for_team(team_id).select_for_update().get(id=run_id)
    except PulseRun.DoesNotExist as error:
        raise PulseOrchestrationConflict("Pulse run was not found.") from error


def _require_before_finalization_cutoff(run: PulseRun, *, now: datetime | None = None) -> None:
    if run.finalization_deadline_at is not None and (now or timezone.now()) >= run.finalization_deadline_at:
        raise PulseOrchestrationConflict("Pulse finalization cutoff has elapsed.")


def bind_pulse_analysis_task(
    *,
    team_id: int,
    run_id: UUID,
    task_id: UUID,
    analysis_task_run_id: UUID,
    reconcile_existing: bool = False,
) -> PulseRun:
    """Bind the one caller-owned analysis task identity before results can be persisted."""
    started = False
    with transaction.atomic():
        run = _get_locked_run(team_id=team_id, run_id=run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            raise PulseOrchestrationConflict("Terminal Pulse runs cannot start analysis.")
        if not reconcile_existing:
            _require_before_finalization_cutoff(run)
        if run.task_id is not None and run.task_id != task_id:
            raise PulseOrchestrationConflict("Pulse task identity does not match its original binding.")
        if run.analysis_task_run_id is not None and run.analysis_task_run_id != analysis_task_run_id:
            raise PulseOrchestrationConflict("Pulse analysis run identity does not match its original binding.")
        update_fields: list[str] = []
        if run.task_id is None:
            run.task_id = task_id
            update_fields.append("task_id")
        if run.analysis_task_run_id is None:
            run.analysis_task_run_id = analysis_task_run_id
            update_fields.append("analysis_task_run_id")
        if run.status == PulseRun.Status.PENDING:
            run.status = PulseRun.Status.ANALYZING
            run.started_at = timezone.now()
            update_fields.extend(["status", "started_at"])
            started = True
        if update_fields:
            run.save(update_fields=[*update_fields, "updated_at"])
        if started:
            transaction.on_commit(lambda: capture_pulse_run_started(team_id=team_id, run_id=run.id))
    return run


def bind_pulse_execution_task(
    *,
    team_id: int,
    run_id: UUID,
    task_id: UUID,
    analysis_task_run_id: UUID,
    execution_task_run_id: UUID,
    publication_lease_id: UUID | None = None,
    reconcile_existing: bool = False,
) -> PulseRun:
    """Bind the one successor run after subscriptions has durably reserved artifacts."""
    with transaction.atomic():
        run = _get_locked_run(team_id=team_id, run_id=run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            raise PulseOrchestrationConflict("Terminal Pulse runs cannot start execution.")
        if run.task_id != task_id or run.analysis_task_run_id != analysis_task_run_id:
            raise PulseOrchestrationConflict("Pulse execution task is not bound to this run.")
        if run.status not in {PulseRun.Status.RESERVING, PulseRun.Status.EXECUTING}:
            raise PulseOrchestrationConflict("Pulse run has not reserved an implementation artifact.")
        if not reconcile_existing:
            _require_before_finalization_cutoff(run)
        if run.execution_task_run_id is not None and run.execution_task_run_id != execution_task_run_id:
            raise PulseOrchestrationConflict("Pulse execution run identity does not match its original binding.")
        draft_artifacts = list(
            Artifact.objects.for_team(team_id).select_for_update().filter(run_id=run.id, kind=Artifact.Kind.DRAFT_PR)
        )
        if len(draft_artifacts) > 1:
            raise PulseOrchestrationConflict("Pulse run has more than one draft pull-request artifact.")
        existing_lease_id = draft_artifacts[0].publication_lease_id if draft_artifacts else None
        if existing_lease_id is not None and existing_lease_id != publication_lease_id:
            raise PulseOrchestrationConflict("Pulse publication lease does not match its original binding.")
        if not draft_artifacts and publication_lease_id is not None:
            raise PulseOrchestrationConflict("Experiment-only Pulse execution cannot bind a publication lease.")
        if run.execution_task_run_id is None:
            run.execution_task_run_id = execution_task_run_id
            run.status = PulseRun.Status.EXECUTING
            run.save(update_fields=["execution_task_run_id", "status", "updated_at"])
        Artifact.objects.for_team(team_id).filter(run_id=run.id, status=Artifact.Status.RESERVED).update(
            execution_task_run_id=execution_task_run_id,
            task_id=task_id,
            status=Artifact.Status.CREATING,
        )
        if publication_lease_id is not None:
            Artifact.objects.for_team(team_id).filter(
                run_id=run.id,
                kind=Artifact.Kind.DRAFT_PR,
                execution_task_run_id=execution_task_run_id,
            ).update(publication_lease_id=publication_lease_id)
        RunAction.objects.for_team(team_id).filter(
            run_id=run.id,
            implementation_selected=True,
            status=RunAction.Status.SELECTED,
        ).update(status=RunAction.Status.EXECUTING)
        return run


def _validate_action_shape(action: PulseAnalysisActionInput) -> None:
    bounded_values = (
        (action.opportunity_key, 512),
        (action.opportunity_title, 400),
        (action.opportunity_summary, 4000),
        (action.action_key, 512),
        (action.title, 400),
        (action.rationale, 4000),
        (action.expected_impact, 2000),
        (action.why_now, 2000),
        (action.metric_name, 255),
        (action.baseline_tool_call_id, 255),
    )
    required_values = bounded_values[:7]
    if any(not isinstance(value, str) or not value or len(value) > limit for value, limit in required_values) or any(
        not isinstance(value, str) or len(value) > limit for value, limit in bounded_values[7:]
    ):
        raise PulseOrchestrationConflict("Pulse analysis action exceeds a bounded field.")
    if type(action.rank) is not int or action.rank < 1 or action.rank > MAX_PULSE_ACTIONS:
        raise PulseOrchestrationConflict("Pulse analysis action rank is invalid.")
    if (
        not isinstance(action.normalized_target, dict)
        or len(action.normalized_target) > MAX_PULSE_ACTION_TARGET_ENTRIES
        or any(
            not isinstance(key, str) or not key or len(key) > 255 or not isinstance(value, str) or len(value) > 512
            for key, value in action.normalized_target.items()
        )
    ):
        raise PulseOrchestrationConflict("Pulse analysis target is invalid.")
    if (
        not isinstance(action.selector, dict)
        or len(action.selector) > MAX_PULSE_ACTION_SELECTOR_ENTRIES
        or any(
            not isinstance(key, str) or not key or len(key) > 255 or not isinstance(value, str) or len(value) > 512
            for key, value in action.selector.items()
        )
    ):
        raise PulseOrchestrationConflict("Pulse analysis measurement selector is invalid.")
    if (
        not isinstance(action.evidence_tool_call_ids, tuple)
        or len(action.evidence_tool_call_ids) > MAX_PULSE_TOOL_CALLS
        or any(not isinstance(item, str) or not item or len(item) > 255 for item in action.evidence_tool_call_ids)
        or len(set(action.evidence_tool_call_ids)) != len(action.evidence_tool_call_ids)
    ):
        raise PulseOrchestrationConflict("Pulse action evidence references are invalid.")


def _validate_action(action: PulseAnalysisActionInput) -> None:
    _validate_action_shape(action)
    if action.effort not in {"small", "medium", "large"}:
        raise PulseOrchestrationConflict("Pulse analysis effort is invalid.")
    if not Decimal(action.confidence).is_finite() or not Decimal("0") <= action.confidence <= Decimal("1"):
        raise PulseOrchestrationConflict("Pulse analysis confidence is invalid.")
    if action.metric_unit not in {"count", "ratio", "percent", "currency", "duration", "other"}:
        raise PulseOrchestrationConflict("Pulse analysis metric unit is invalid.")
    if action.metric_direction not in {"increase", "decrease", "maintain"}:
        raise PulseOrchestrationConflict("Pulse analysis metric direction is invalid.")
    if action.expected_change_type not in {"absolute", "relative_percent"} or action.readout_after_days not in {
        3,
        7,
        14,
        28,
    }:
        raise PulseOrchestrationConflict("Pulse analysis measurement configuration is invalid.")
    if (
        not action.expected_change_lower.is_finite()
        or not action.expected_change_upper.is_finite()
        or action.expected_change_lower > action.expected_change_upper
    ):
        raise PulseOrchestrationConflict("Pulse analysis forecast range is invalid.")
    if action.baseline_tool_call_id not in action.evidence_tool_call_ids:
        raise PulseOrchestrationConflict("Pulse baseline evidence must be included in action evidence.")


def _evidence_set_for_action(*, run: PulseRun, action: PulseAnalysisActionInput) -> EvidenceSet | None:
    if not action.evidence_tool_call_ids:
        return None
    calls = list(
        EvidenceToolCall.objects.for_team(run.team_id).filter(
            run_id=run.id,
            tool_call_id__in=action.evidence_tool_call_ids,
            completed_at__isnull=False,
            actor_id=run.config_snapshot.get("actor_id"),
        )
    )
    if len(calls) != len(action.evidence_tool_call_ids):
        raise PulseOrchestrationConflict("Pulse action evidence is unavailable.")
    by_id = {call.tool_call_id: call for call in calls}
    if any(
        not call.normalized_result_ref.startswith("sha256:")
        or len(call.normalized_result_ref) != 71
        or any(character not in "0123456789abcdef" for character in call.normalized_result_ref[7:])
        for call in calls
    ):
        raise PulseOrchestrationConflict("Pulse action evidence result is invalid.")
    refs: list[dict[str, str]] = []
    for tool_call_id in sorted(action.evidence_tool_call_ids):
        call = by_id[tool_call_id]
        completed_at = call.completed_at
        if completed_at is None:
            raise PulseOrchestrationConflict("Pulse action evidence is incomplete.")
        refs.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": call.tool_name,
                "tool_schema_version": call.tool_schema_version,
                "completed_at": completed_at.isoformat(),
                "result_hash": call.normalized_result_ref,
            }
        )
    content_hash = sha256(json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    evidence_set, _ = EvidenceSet.objects.for_team(run.team_id).get_or_create(
        team_id=run.team_id, run=run, content_hash=content_hash, defaults={"item_refs": refs}
    )
    if evidence_set.item_refs != refs:
        raise PulseOrchestrationConflict("Pulse action evidence retry conflicts.")
    return evidence_set


def _artifact_kinds(action: PulseAnalysisActionInput) -> tuple[str, ...]:
    if action.kind == "combined":
        return (Artifact.Kind.DRAFT_PR, Artifact.Kind.EXPERIMENT_DRAFT)
    if action.kind == "draft_pr":
        return (Artifact.Kind.DRAFT_PR,)
    if action.kind == "experiment_draft":
        return (Artifact.Kind.EXPERIMENT_DRAFT,)
    return ()


def _require_existing_action_matches(action: RunAction, input: PulseAnalysisActionInput, selected: bool) -> None:
    if (
        action.kind != input.kind
        or action.title != input.title
        or action.rationale != input.rationale
        or action.expected_impact != input.expected_impact
        or action.rank != input.rank
        or action.implementation_selected != selected
        or action.why_now != input.why_now
        or action.confidence != float(input.confidence)
        or action.effort != input.effort
        or action.metric_name != input.metric_name
        or action.metric_unit != input.metric_unit
        or action.metric_direction != input.metric_direction
        or action.expected_change_type != input.expected_change_type
        or action.expected_change_lower != input.expected_change_lower
        or action.expected_change_upper != input.expected_change_upper
        or action.readout_after_days != input.readout_after_days
    ):
        raise PulseOrchestrationConflict("Pulse action retry does not match its original binding.")


def persist_pulse_analysis(input: PulseAnalysisPersistenceInput) -> PulseAnalysisPersistenceDTO:
    """Persist at most three ranked actions and reserve selected server-owned artifacts."""
    terminal_status: str | None = None
    with transaction.atomic():
        run = _get_locked_run(team_id=input.team_id, run_id=input.run_id)
        limits = run.config_snapshot.get("limits", {})
        max_actions = limits.get("max_actions", MAX_PULSE_ACTIONS) if isinstance(limits, dict) else MAX_PULSE_ACTIONS
        if len(input.actions) > max_actions or len(input.readouts) > 10:
            raise PulseOrchestrationConflict("Pulse analysis returned too many actions.")
        if run.task_id != input.task_id or run.analysis_task_run_id != input.analysis_task_run_id:
            raise PulseOrchestrationConflict("Pulse analysis task is not bound to this run.")
        if run.status not in {PulseRun.Status.ANALYZING, PulseRun.Status.RESERVING}:
            raise PulseOrchestrationConflict("Pulse run is not ready to persist analysis.")
        flags = run.config_snapshot.get("flags")
        if not isinstance(flags, dict):
            raise PulseOrchestrationConflict("Pulse run capability snapshot is invalid.")
        if input.readouts and flags.get("allow_outcome_readouts") is True:
            persist_outcome_readouts(
                PulseOutcomeReadoutPersistenceInput(
                    team_id=input.team_id, run_id=run.id, now=timezone.now(), readouts=input.readouts
                )
            )

        action_ids: list[UUID] = []
        artifact_ids: list[UUID] = []
        selected_persisted = False
        for action_input in sorted(input.actions, key=lambda action: action.rank):
            try:
                _validate_action(action_input)
            except PulseOrchestrationConflict:
                continue
            measurement = None
            if flags.get("allow_outcome_readouts") is True:
                try:
                    evidence_set = _evidence_set_for_action(run=run, action=action_input)
                    measurement = canonicalize_measurement(
                        candidate=MeasurementCandidate(
                            run_id=run.id,
                            baseline_tool_call_id=action_input.baseline_tool_call_id,
                            metric_name=action_input.metric_name,
                            metric_unit=cast(
                                Literal["count", "ratio", "percent", "currency", "duration", "other"],
                                action_input.metric_unit,
                            ),
                            direction=cast(Literal["increase", "decrease", "maintain"], action_input.metric_direction),
                            expected_change_type=cast(
                                Literal["absolute", "relative_percent"], action_input.expected_change_type
                            ),
                            expected_change_lower=action_input.expected_change_lower,
                            expected_change_upper=action_input.expected_change_upper,
                            readout_after_days=action_input.readout_after_days,
                            selector=action_input.selector,
                        ),
                        evidence=load_measurement_evidence(
                            team_id=input.team_id, run_id=run.id, tool_call_id=action_input.baseline_tool_call_id
                        ),
                    )
                except (PulseOrchestrationConflict, PulseOutcomeConflict, MeasurementValidationError):
                    continue
                action_input = replace(
                    action_input,
                    metric_name=measurement.metric_name,
                    metric_unit=measurement.metric_unit,
                )
            else:
                evidence_set = _evidence_set_for_action(run=run, action=action_input)
            selected = action_input.kind != "recommendation" and not selected_persisted
            selected_kinds = _artifact_kinds(action_input)
            if Artifact.Kind.DRAFT_PR in selected_kinds and flags.get("allow_draft_pr") is not True:
                selected = False
            if Artifact.Kind.EXPERIMENT_DRAFT in selected_kinds and flags.get("allow_experiment_draft") is not True:
                selected = False
            proposal_metric_identity = (
                measurement_identity(specification=measurement.spec)
                if measurement is not None
                else action_input.metric_name
            )
            proposal_key = (
                stable_action_key(
                    kind=action_input.kind,
                    normalized_target=action_input.normalized_target,
                    metric_name=proposal_metric_identity,
                )
                if proposal_metric_identity
                else action_input.action_key
            )
            Team.objects.select_for_update(of=("self",)).get(id=input.team_id)
            proposal = (
                ActionProposal.objects.for_team(input.team_id)
                .select_for_update()
                .select_related("opportunity")
                .filter(stable_action_key=proposal_key, kind=action_input.kind)
                .order_by("created_at")
                .first()
            )
            proposal_created = proposal is None
            if proposal is None:
                opportunity, _ = Opportunity.objects.for_team(input.team_id).get_or_create(
                    team_id=input.team_id,
                    stable_key=action_input.opportunity_key,
                    defaults={"title": action_input.opportunity_title, "summary": action_input.opportunity_summary},
                )
                proposal = ActionProposal.objects.for_team(input.team_id).create(
                    team_id=input.team_id,
                    opportunity=opportunity,
                    stable_action_key=proposal_key,
                    kind=action_input.kind,
                    normalized_target=action_input.normalized_target,
                )
            else:
                opportunity = proposal.opportunity
                opportunity.title = action_input.opportunity_title
                opportunity.summary = action_input.opportunity_summary
                opportunity.save(update_fields=["title", "summary", "last_seen_at", "updated_at"])
            if not proposal_created and proposal.normalized_target != action_input.normalized_target:
                raise PulseOrchestrationConflict("Pulse proposal retry does not match its original binding.")
            if not proposal_created:
                proposal.save(update_fields=["last_seen_at", "updated_at"])
                suppress_after = timezone.now() - timedelta(days=90)
                same_run_action_exists = (
                    RunAction.objects.for_team(input.team_id)
                    .filter(run=run, action_key=action_input.action_key)
                    .exists()
                )
                if not same_run_action_exists and (
                    OutcomePlan.objects.for_team(input.team_id)
                    .select_for_update()
                    .filter(proposal=proposal)
                    .filter(
                        models.Q(readout_status__in=["waiting", "scheduled", "due", "measuring"])
                        | models.Q(
                            models.Q(readout_status__in=["measured", "inconclusive", "cancelled"])
                            | models.Q(adoption_status__in=["dismissed", "abandoned"]),
                            models.Q(completed_at__gte=suppress_after)
                            | models.Q(completed_at__isnull=True, updated_at__gte=suppress_after),
                        )
                    )
                    .exists()
                ):
                    transaction.on_commit(
                        lambda: capture_pulse_outcome(
                            team_id=input.team_id,
                            run_id=run.id,
                            event="pulse_outcome_suppressed",
                            status="suppressed",
                        )
                    )
                    continue
            run_action, action_created = RunAction.objects.for_team(input.team_id).get_or_create(
                team_id=input.team_id,
                run=run,
                action_key=action_input.action_key,
                defaults={
                    "opportunity": opportunity,
                    "proposal": proposal,
                    "kind": action_input.kind,
                    "title": action_input.title,
                    "rationale": action_input.rationale,
                    "expected_impact": action_input.expected_impact,
                    "why_now": action_input.why_now,
                    "confidence": float(action_input.confidence),
                    "effort": action_input.effort,
                    "metric_name": action_input.metric_name,
                    "metric_unit": action_input.metric_unit,
                    "metric_direction": action_input.metric_direction,
                    "expected_change_type": action_input.expected_change_type,
                    "expected_change_lower": action_input.expected_change_lower,
                    "expected_change_upper": action_input.expected_change_upper,
                    "readout_after_days": action_input.readout_after_days,
                    "rank": action_input.rank,
                    "implementation_selected": selected,
                    "evidence_set": evidence_set,
                    "status": RunAction.Status.SELECTED if selected else RunAction.Status.PROPOSED,
                },
            )
            if not action_created:
                _require_existing_action_matches(run_action, action_input, selected)
                if run_action.evidence_set_id != (evidence_set.id if evidence_set is not None else None):
                    raise PulseOrchestrationConflict("Pulse action evidence retry conflicts.")
            action_ids.append(run_action.id)
            if flags.get("allow_outcome_readouts") is True and action_created and measurement is not None:
                create_outcome_plan(action=run_action, measurement=measurement)
            if not selected:
                continue
            _require_before_finalization_cutoff(run)
            selected_persisted = True
            for artifact_kind in _artifact_kinds(action_input):
                try:
                    with transaction.atomic():
                        artifact, _ = Artifact.objects.for_team(input.team_id).get_or_create(
                            team_id=input.team_id,
                            run=run,
                            kind=artifact_kind,
                            defaults={
                                "action": run_action,
                                "opportunity": opportunity,
                                "proposal": proposal,
                                "idempotency_key": f"pulse:{run.id}:{run_action.action_key}:{artifact_kind}",
                                "active_claim": artifact_kind == Artifact.Kind.DRAFT_PR,
                                "status": Artifact.Status.RESERVED,
                            },
                        )
                except IntegrityError as error:
                    raise PulseOrchestrationConflict("Pulse artifact is already actively claimed.") from error
                if artifact.action_id != run_action.id or artifact.proposal_id != proposal.id:
                    raise PulseOrchestrationConflict("Pulse artifact retry does not match its original binding.")
                artifact_ids.append(artifact.id)

        if selected_persisted:
            run.status = PulseRun.Status.RESERVING
            run.save(update_fields=["status", "updated_at"])
        else:
            run.status = PulseRun.Status.COMPLETED
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at", "updated_at"])
            terminal_status = run.status
        result = PulseAnalysisPersistenceDTO(
            run_id=run.id,
            action_ids=tuple(action_ids),
            artifact_ids=tuple(artifact_ids),
        )
        if terminal_status is not None:
            transaction.on_commit(
                lambda: capture_pulse_run_terminalized(team_id=input.team_id, run_id=run.id, status=terminal_status)
            )
    return result


def request_pulse_run_cancellation(
    *,
    team_id: int,
    run_id: UUID,
    now: datetime | None = None,
) -> PulseRun:
    """Durably record a cancellation request before a caller asks Tasks to stop work."""
    current_time = now or timezone.now()
    with transaction.atomic():
        run = _get_locked_run(team_id=team_id, run_id=run_id)
        if run.status in _TERMINAL_RUN_STATUSES or run.cancellation_requested_at is not None:
            return run
        run.cancellation_requested_at = current_time
        run.save(update_fields=["cancellation_requested_at", "updated_at"])
        return run


def converge_pulse_artifacts_for_terminalization(*, artifacts: list[Artifact], failure_code: str) -> None:
    """Resolve known-abandoned reservations without releasing uncertain publication claims."""
    for artifact in artifacts:
        if (
            artifact.status == Artifact.Status.RESERVED
            and artifact.execution_task_run_id is None
            and artifact.publication_lease_id is None
        ):
            artifact.status = Artifact.Status.FAILED
            artifact.failure_code = "artifact_creation_abandoned"
            artifact.active_claim = False
            artifact.save(update_fields=["status", "failure_code", "active_claim", "updated_at"])
        elif artifact.status in {Artifact.Status.RESERVED, Artifact.Status.CREATING}:
            artifact.status = Artifact.Status.PUBLICATION_UNKNOWN
            artifact.failure_code = failure_code
            artifact.save(update_fields=["status", "failure_code", "updated_at"])


def reconcile_pulse_draft_publication(*, team_id: int, run_id: UUID, now: datetime | None = None) -> bool:
    """Converge one exact Tasks-owned draft publication into subscription state."""
    run = (
        PulseRun.objects.for_team(team_id)
        .filter(id=run_id)
        .only("id", "task_id", "analysis_task_run_id", "execution_task_run_id")
        .first()
    )
    if run is None or run.task_id is None or run.analysis_task_run_id is None or run.execution_task_run_id is None:
        return False
    artifact = (
        Artifact.objects.for_team(team_id)
        .filter(
            run_id=run.id,
            kind=Artifact.Kind.DRAFT_PR,
            status=Artifact.Status.CREATING,
            task_id=run.task_id,
            execution_task_run_id=run.execution_task_run_id,
            publication_lease_id__isnull=False,
        )
        .only("id", "publication_lease_id")
        .first()
    )
    if artifact is None or artifact.publication_lease_id is None:
        return False
    publication = tasks_facade.get_staged_draft_publication(
        tasks_contracts.GetStagedDraftPublicationInput(
            team_id=team_id,
            caller_id=run.id,
            task_id=run.task_id,
            source_run_id=run.analysis_task_run_id,
            execution_run_id=run.execution_task_run_id,
            publication_lease_id=artifact.publication_lease_id,
        )
    )
    if publication is None:
        return False
    with transaction.atomic():
        locked_run = PulseRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        if (
            locked_run.task_id != run.task_id
            or locked_run.analysis_task_run_id != run.analysis_task_run_id
            or locked_run.execution_task_run_id != run.execution_task_run_id
        ):
            return False
        locked_artifact = (
            Artifact.objects.for_team(team_id)
            .select_for_update()
            .filter(
                id=artifact.id,
                run_id=locked_run.id,
                status=Artifact.Status.CREATING,
                task_id=locked_run.task_id,
                execution_task_run_id=locked_run.execution_task_run_id,
                publication_lease_id=artifact.publication_lease_id,
            )
            .first()
        )
        if locked_artifact is None:
            return False
        if publication.status == "finalized" and publication.pr_url:
            locked_artifact.external_id = str(publication.pr_number) if publication.pr_number is not None else None
            locked_artifact.external_url = publication.pr_url
            locked_artifact.status = Artifact.Status.VERIFIED
            locked_artifact.verified_at = now or timezone.now()
            locked_artifact.failure_code = None
            locked_artifact.save(
                update_fields=[
                    "external_id",
                    "external_url",
                    "status",
                    "verified_at",
                    "failure_code",
                    "updated_at",
                ]
            )
            return True
        if publication.status in {"blocked", "revoked"}:
            locked_artifact.status = Artifact.Status.FAILED
            locked_artifact.failure_code = f"publication_{publication.status}"
            locked_artifact.active_claim = False
            locked_artifact.save(update_fields=["status", "failure_code", "active_claim", "updated_at"])
            return True
        if publication.status == "publication_unknown":
            locked_artifact.status = Artifact.Status.PUBLICATION_UNKNOWN
            locked_artifact.failure_code = "publication_unknown"
            locked_artifact.save(update_fields=["status", "failure_code", "updated_at"])
            return True
    return False


def reconcile_pulse_task_terminal_state(
    *,
    team_id: int,
    run_id: UUID,
    task_run_id: UUID,
    task_status: str,
    now: datetime | None = None,
    failure_code: str | None = None,
) -> PulseRun:
    """Finalize a bound run from an authoritative terminal Tasks facade result."""
    current_time = now or timezone.now()
    terminal_status: str | None = None
    with transaction.atomic():
        run = _get_locked_run(team_id=team_id, run_id=run_id)
        expected_task_run_id = run.execution_task_run_id or run.analysis_task_run_id
        if expected_task_run_id != task_run_id or run.status in _TERMINAL_RUN_STATUSES:
            return run
        artifacts = list(Artifact.objects.for_team(team_id).select_for_update().filter(run_id=run.id))
        deadline_elapsed = run.finalization_deadline_at is not None and current_time >= run.finalization_deadline_at
        needs_terminalization = (
            deadline_elapsed or task_status != "completed" or run.cancellation_requested_at is not None
        )
        if needs_terminalization:
            converge_pulse_artifacts_for_terminalization(
                artifacts=artifacts,
                failure_code="finalization_timeout" if deadline_elapsed else (failure_code or "task_terminal"),
            )
        if any(artifact.status == Artifact.Status.CREATING for artifact in artifacts):
            return run
        if task_status == "completed":
            run.status = (
                PulseRun.Status.COMPLETED
                if all(artifact.status == Artifact.Status.VERIFIED for artifact in artifacts)
                else PulseRun.Status.PARTIAL
            )
        elif task_status == "cancelled" or run.cancellation_requested_at is not None:
            run.status = (
                PulseRun.Status.PARTIAL
                if any(artifact.status == Artifact.Status.VERIFIED for artifact in artifacts)
                else PulseRun.Status.CANCELLED
            )
        elif task_status in _TASK_FAILED_STATUSES:
            run.status = (
                PulseRun.Status.PARTIAL
                if any(artifact.status == Artifact.Status.VERIFIED for artifact in artifacts)
                else PulseRun.Status.FAILED
            )
        else:
            raise PulseOrchestrationConflict("Tasks reported a non-terminal Pulse status.")
        run.finished_at = current_time
        update_fields = ["status", "finished_at", "updated_at"]
        if failure_code is not None:
            run.failure_code = failure_code
            update_fields.append("failure_code")
        run.save(update_fields=update_fields)
        action_status = (
            RunAction.Status.COMPLETED
            if run.status == PulseRun.Status.COMPLETED
            else RunAction.Status.FAILED
            if run.status in {PulseRun.Status.FAILED, PulseRun.Status.PARTIAL}
            else RunAction.Status.SKIPPED
        )
        RunAction.objects.for_team(team_id).filter(
            run_id=run.id,
            implementation_selected=True,
            status__in={RunAction.Status.SELECTED, RunAction.Status.EXECUTING},
        ).update(status=action_status)
        terminal_status = run.status
        if terminal_status is not None:
            transaction.on_commit(
                lambda: capture_pulse_run_terminalized(team_id=team_id, run_id=run.id, status=terminal_status)
            )
    return run
