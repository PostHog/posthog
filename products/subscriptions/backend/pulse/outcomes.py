"""Transactional outcome-plan persistence and measurement state transitions."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from products.subscriptions.backend.models import (
    EvidenceRawBody,
    EvidenceSet,
    EvidenceToolCall,
    OutcomeObservation,
    OutcomePlan,
    PulseRun,
    RunAction,
)

from .contracts import (
    CanonicalMeasurement,
    ClaimedOutcomeDTO,
    MeasurementEvidence,
    OutcomeObservationDTO,
    PulseOutcomeReadoutInput,
    PulseOutcomeReadoutPersistenceInput,
)
from .measurements import evaluate_measurement
from .telemetry import capture_pulse_outcome

OUTCOME_NOT_READY_MAX_AGE = timedelta(days=90)
OUTCOME_SUPPRESSION_WINDOW = timedelta(days=90)
_NOT_READY_RETRY_DELAY = timedelta(days=1)
_MAX_CLAIM_LIMIT = 10
_MAX_ATTEMPTS = 2
_MAX_CLAIM_EXPIRY_SECONDS = 24 * 60 * 60


class PulseOutcomeConflict(ValueError):
    pass


def claim_due_outcomes(
    *, team_id: int, subscription_id: int, run_id: UUID, now: datetime, limit: int
) -> tuple[ClaimedOutcomeDTO, ...]:
    """Claim due plans with short row locks; a claim never counts as an attempt."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return ()
    if not hasattr(now, "tzinfo") or now.tzinfo is None:
        raise PulseOutcomeConflict("Outcome claim time must include a timezone.")
    claim_limit = min(limit, _MAX_CLAIM_LIMIT)
    expiry = now - timedelta(
        seconds=_bounded_setting("PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS", 7200, _MAX_CLAIM_EXPIRY_SECONDS)
    )
    with transaction.atomic():
        if (
            not PulseRun.objects.for_team(team_id)
            .filter(id=run_id, subscription_id=subscription_id, status=PulseRun.Status.PENDING)
            .exists()
        ):
            raise PulseOutcomeConflict("Outcome claim run is not eligible for this subscription.")
        candidates = list(
            OutcomePlan.objects.for_team(team_id)
            .select_for_update(skip_locked=True)
            .filter(subscription_id=subscription_id)
            .filter(
                Q(
                    readout_status=OutcomePlan.ReadoutStatus.DUE,
                    next_readout_at__lte=now,
                )
                | Q(
                    readout_status=OutcomePlan.ReadoutStatus.DUE,
                    next_readout_at__isnull=True,
                )
                | Q(readout_status=OutcomePlan.ReadoutStatus.MEASURING, claimed_at__lte=expiry)
                | Q(readout_status=OutcomePlan.ReadoutStatus.MEASURING, claimed_at__isnull=True)
            )
            .order_by("next_readout_at", "created_at")[:claim_limit]
        )
        claimed: list[ClaimedOutcomeDTO] = []
        for plan in candidates:
            is_due = plan.readout_status == OutcomePlan.ReadoutStatus.DUE
            is_expired = plan.readout_status == OutcomePlan.ReadoutStatus.MEASURING and (
                plan.claimed_at is None or plan.claimed_at <= expiry
            )
            if not (is_due or is_expired):
                continue
            plan.readout_status = OutcomePlan.ReadoutStatus.MEASURING
            plan.claimed_by_run_id = run_id
            plan.claimed_at = now
            plan.save(update_fields=["readout_status", "claimed_by_run", "claimed_at", "updated_at"])
            specification = plan.measurement_spec
            version = specification.get("version") if isinstance(specification, dict) else None
            claimed.append(
                ClaimedOutcomeDTO(
                    plan_id=plan.id,
                    source_action_id=plan.source_action_id,
                    measurement_spec_version=version if isinstance(version, int) else 0,
                )
            )

            def capture_claimed_outcome(*, plan_id: UUID = plan.id, reclaimed: bool = not is_due) -> None:
                capture_pulse_outcome(
                    team_id=team_id,
                    run_id=run_id,
                    event="pulse_outcome_claimed",
                    plan_id=plan_id,
                    status="reclaimed" if reclaimed else "claimed",
                )

            transaction.on_commit(capture_claimed_outcome)
    return tuple(claimed)


def claim_outcomes_for_run_snapshot(
    *, team_id: int, subscription_id: int, run_id: UUID, now: datetime
) -> tuple[ClaimedOutcomeDTO, ...]:
    """Fix a delivery's bounded claim references once, without changing retry input."""
    with transaction.atomic():
        run = PulseRun.objects.for_team(team_id).select_for_update().get(id=run_id, subscription_id=subscription_id)
        snapshot = dict(run.config_snapshot) if isinstance(run.config_snapshot, dict) else {}
        existing = snapshot.get("claimed_outcomes")
        if isinstance(existing, list):
            return tuple(
                ClaimedOutcomeDTO(
                    plan_id=UUID(item["plan_id"]),
                    source_action_id=UUID(item["source_action_id"]),
                    measurement_spec_version=item["measurement_spec_version"],
                )
                for item in existing
                if isinstance(item, dict)
                and set(item) == {"plan_id", "source_action_id", "measurement_spec_version"}
                and isinstance(item.get("plan_id"), str)
                and isinstance(item.get("source_action_id"), str)
                and isinstance(item.get("measurement_spec_version"), int)
            )
        if run.status != PulseRun.Status.PENDING:
            raise PulseOutcomeConflict("Outcome claim run is not eligible for this subscription.")
        flags = snapshot.get("flags")
        limits = snapshot.get("limits")
        if not isinstance(flags, dict) or flags.get("allow_outcome_readouts") is not True:
            return ()
        limit = limits.get("max_due_readouts", 3) if isinstance(limits, dict) else 3
        claims = claim_due_outcomes(
            team_id=team_id, subscription_id=subscription_id, run_id=run_id, now=now, limit=limit
        )
        snapshot["claimed_outcomes"] = [
            {
                "plan_id": str(item.plan_id),
                "source_action_id": str(item.source_action_id),
                "measurement_spec_version": item.measurement_spec_version,
            }
            for item in claims
        ]
        run.config_snapshot = snapshot
        run.save(update_fields=["config_snapshot", "updated_at"])
        return claims


def create_outcome_plan(*, action: RunAction, measurement: CanonicalMeasurement) -> OutcomePlan:
    """Create the one active plan for a valid, server-canonical recommendation."""
    if action.proposal_id is None or action.run_id is None:
        raise PulseOutcomeConflict("Outcome action is not durably bound.")
    subscription_id = action.run.subscription_id
    team_id = action.team_id
    active_count = (
        OutcomePlan.objects.for_team(team_id)
        .filter(
            subscription_id=subscription_id,
            readout_status__in=[
                OutcomePlan.ReadoutStatus.WAITING,
                OutcomePlan.ReadoutStatus.SCHEDULED,
                OutcomePlan.ReadoutStatus.DUE,
                OutcomePlan.ReadoutStatus.MEASURING,
            ],
        )
        .count()
    )
    if active_count >= _bounded_setting("PULSE_MAX_ACTIVE_OUTCOME_PLANS", 20, 100):
        raise PulseOutcomeConflict("Outcome plan capacity is exhausted.")
    try:
        plan = OutcomePlan.objects.for_team(team_id).create(
            team_id=team_id,
            subscription_id=subscription_id,
            proposal_id=action.proposal_id,
            source_action=action,
            measurement_spec=measurement.spec,
            baseline_value=measurement.baseline_value,
            baseline_from=measurement.baseline_from,
            baseline_to=measurement.baseline_to,
        )
        transaction.on_commit(
            lambda: capture_pulse_outcome(
                team_id=team_id, run_id=action.run_id, event="pulse_outcome_plan_created", plan_id=plan.id
            )
        )
        return plan
    except IntegrityError as error:
        raise PulseOutcomeConflict("Outcome plan is already active for this proposal.") from error


def adopt_outcome_plan(*, team_id: int, plan_id: UUID, source: str, adopted_at: datetime, now: datetime) -> bool:
    """Atomically adopt a pending plan once and schedule its one readout."""
    if source not in {
        OutcomePlan.AdoptionSource.PULL_REQUEST_MERGED,
        OutcomePlan.AdoptionSource.EXPERIMENT_LAUNCHED,
    }:
        raise PulseOutcomeConflict("Outcome adoption source is invalid.")
    with transaction.atomic():
        plan = OutcomePlan.objects.for_team(team_id).select_for_update().filter(id=plan_id).first()
        if plan is None or plan.adoption_status != OutcomePlan.AdoptionStatus.PENDING:
            return False
        delay = plan.source_action.readout_after_days
        if delay not in {3, 7, 14, 28}:
            raise PulseOutcomeConflict("Outcome action has no valid readout delay.")
        plan.adoption_status = OutcomePlan.AdoptionStatus.ADOPTED
        plan.adoption_source = source
        plan.adopted_at = adopted_at
        plan.readout_status = OutcomePlan.ReadoutStatus.SCHEDULED
        plan.next_readout_at = adopted_at + timedelta(days=delay)
        plan.completed_at = None
        plan.save(
            update_fields=[
                "adoption_status",
                "adoption_source",
                "adopted_at",
                "readout_status",
                "next_readout_at",
                "completed_at",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: capture_pulse_outcome(
                team_id=team_id,
                run_id=plan.source_action.run_id,
                event="pulse_outcome_adoption",
                plan_id=plan.id,
                status="adopted",
                delay_days=delay,
                source=source,
            )
        )
        return True


def decide_outcome_plan(
    *, team_id: int, plan_id: UUID, decision: Literal["adopted", "dismissed"], actor_id: int, now: datetime
) -> OutcomePlan:
    """Record a person's advice decision before any outcome observation exists."""
    with transaction.atomic():
        try:
            plan = (
                OutcomePlan.objects.for_team(team_id)
                .select_for_update()
                .select_related("source_action")
                .get(id=plan_id)
            )
        except OutcomePlan.DoesNotExist as error:
            raise PulseOutcomeConflict("Outcome plan was not found.") from error
        if decision == "adopted":
            if plan.adoption_status == OutcomePlan.AdoptionStatus.ADOPTED:
                return plan
        elif plan.adoption_status == OutcomePlan.AdoptionStatus.DISMISSED:
            return plan
        if OutcomeObservation.objects.for_team(team_id).filter(plan_id=plan.id).exists() or plan.readout_status in {
            OutcomePlan.ReadoutStatus.MEASURING,
            OutcomePlan.ReadoutStatus.MEASURED,
            OutcomePlan.ReadoutStatus.INCONCLUSIVE,
        }:
            raise PulseOutcomeConflict("Measured outcomes cannot be manually changed.")
        if decision == "adopted":
            delay = plan.source_action.readout_after_days
            if delay not in {3, 7, 14, 28}:
                raise PulseOutcomeConflict("Outcome action has no valid readout delay.")
            plan.adoption_status = OutcomePlan.AdoptionStatus.ADOPTED
            plan.adoption_source = OutcomePlan.AdoptionSource.MANUAL
            plan.adopted_at = now
            plan.decided_by_id = actor_id
            plan.readout_status = OutcomePlan.ReadoutStatus.SCHEDULED
            plan.next_readout_at = now + timedelta(days=delay)
            plan.completed_at = None
            plan.claimed_by_run_id = None
            plan.claimed_at = None
        else:
            if plan.adoption_status == OutcomePlan.AdoptionStatus.DISMISSED:
                return plan
            plan.adoption_status = OutcomePlan.AdoptionStatus.DISMISSED
            plan.adoption_source = OutcomePlan.AdoptionSource.MANUAL
            plan.adopted_at = None
            plan.decided_by_id = actor_id
            plan.readout_status = OutcomePlan.ReadoutStatus.CANCELLED
            plan.next_readout_at = None
            plan.completed_at = now
            plan.claimed_by_run_id = None
            plan.claimed_at = None
        plan.save(
            update_fields=[
                "adoption_status",
                "adoption_source",
                "adopted_at",
                "decided_by_id",
                "readout_status",
                "next_readout_at",
                "completed_at",
                "claimed_by_run",
                "claimed_at",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: capture_pulse_outcome(
                team_id=team_id,
                run_id=plan.source_action.run_id,
                event="pulse_outcome_adoption",
                plan_id=plan.id,
                status=decision,
                source=OutcomePlan.AdoptionSource.MANUAL,
            )
        )
        return plan


def abandon_outcome_plan(*, team_id: int, plan_id: UUID, now: datetime, reason: str) -> bool:
    """Cancel an unadopted plan when its exact prepared artifact is abandoned."""
    with transaction.atomic():
        plan = OutcomePlan.objects.for_team(team_id).select_for_update().filter(id=plan_id).first()
        if plan is None or plan.adoption_status != OutcomePlan.AdoptionStatus.PENDING:
            return False
        plan.adoption_status = OutcomePlan.AdoptionStatus.ABANDONED
        plan.readout_status = OutcomePlan.ReadoutStatus.CANCELLED
        plan.next_readout_at = None
        plan.claimed_by_run_id = None
        plan.claimed_at = None
        plan.completed_at = now
        plan.save(
            update_fields=[
                "adoption_status",
                "readout_status",
                "next_readout_at",
                "claimed_by_run",
                "claimed_at",
                "completed_at",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: capture_pulse_outcome(
                team_id=team_id,
                run_id=plan.source_action.run_id,
                event="pulse_outcome_adoption",
                plan_id=plan.id,
                status="abandoned",
                source=reason,
            )
        )
        return True


def mark_due_or_release_expired_outcome_plan(*, team_id: int, plan_id: UUID, now: datetime) -> bool:
    """Make scheduled plans due and release stale claims without measuring them."""
    expiry = now - timedelta(
        seconds=_bounded_setting("PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS", 7200, _MAX_CLAIM_EXPIRY_SECONDS)
    )
    with transaction.atomic():
        plan = OutcomePlan.objects.for_team(team_id).select_for_update().filter(id=plan_id).first()
        if plan is None:
            return False
        if plan.readout_status == OutcomePlan.ReadoutStatus.SCHEDULED and plan.next_readout_at is not None:
            if now < plan.next_readout_at:
                return False
            plan.readout_status = OutcomePlan.ReadoutStatus.DUE
            plan.save(update_fields=["readout_status", "updated_at"])
            return True
        if plan.readout_status == OutcomePlan.ReadoutStatus.MEASURING and (
            plan.claimed_at is None or plan.claimed_at <= expiry
        ):
            plan.readout_status = OutcomePlan.ReadoutStatus.DUE
            plan.claimed_by_run_id = None
            plan.claimed_at = None
            plan.save(update_fields=["readout_status", "claimed_by_run", "claimed_at", "updated_at"])
            return True
    return False


def persist_outcome_readouts(input: PulseOutcomeReadoutPersistenceInput) -> tuple[OutcomeObservationDTO, ...]:
    """Persist claimed outcomes exactly once, releasing only safe retry states."""
    if len(input.readouts) > _MAX_CLAIM_LIMIT or len({item.plan_id for item in input.readouts}) != len(input.readouts):
        raise PulseOutcomeConflict("Outcome readouts must be unique and bounded.")
    observations: list[OutcomeObservationDTO] = []
    with transaction.atomic():
        if not PulseRun.objects.for_team(input.team_id).filter(id=input.run_id).exists():
            raise PulseOutcomeConflict("Outcome readout run was not found.")
        for readout in input.readouts:
            try:
                with transaction.atomic():
                    observation = _persist_readout(input=input, readout=readout)
            except PulseOutcomeConflict:
                continue
            if observation is not None:
                observations.append(observation)
    return tuple(observations)


def _persist_readout(
    *, input: PulseOutcomeReadoutPersistenceInput, readout: PulseOutcomeReadoutInput
) -> OutcomeObservationDTO | None:
    try:
        plan = (
            OutcomePlan.objects.for_team(input.team_id)
            .select_for_update()
            .select_related("source_action")
            .get(id=readout.plan_id)
        )
    except OutcomePlan.DoesNotExist as error:
        raise PulseOutcomeConflict("Outcome plan was not found.") from error
    if plan.readout_status != OutcomePlan.ReadoutStatus.MEASURING or plan.claimed_by_run_id != input.run_id:
        raise PulseOutcomeConflict("Outcome plan is not claimed by this run.")
    if readout.not_ready:
        if readout.evidence_tool_call_id is not None or readout.failure_code is not None:
            raise PulseOutcomeConflict("Not-ready outcomes cannot include measurement results.")
        adopted_at = plan.adopted_at or plan.next_readout_at
        if adopted_at is not None and input.now - adopted_at >= OUTCOME_NOT_READY_MAX_AGE:
            return _terminal_inconclusive(
                plan=plan, run_id=input.run_id, failure_code="not_ready_expired", now=input.now
            )
        plan.readout_status = OutcomePlan.ReadoutStatus.DUE
        plan.next_readout_at = input.now + _NOT_READY_RETRY_DELAY
        plan.claimed_by_run_id = None
        plan.claimed_at = None
        plan.last_failure_code = "not_ready"
        plan.save(
            update_fields=[
                "readout_status",
                "next_readout_at",
                "claimed_by_run",
                "claimed_at",
                "last_failure_code",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: capture_pulse_outcome(
                team_id=plan.team_id,
                run_id=input.run_id,
                event="pulse_outcome_attempted",
                plan_id=plan.id,
                status="not_ready",
            )
        )
        return None
    if readout.failure_code is not None:
        if (
            readout.evidence_tool_call_id is not None
            or not readout.failure_code.isidentifier()
            or len(readout.failure_code) > 128
        ):
            raise PulseOutcomeConflict("Outcome failure classification is invalid.")
        return _failed_measurement(plan=plan, run_id=input.run_id, failure_code=readout.failure_code, now=input.now)
    if readout.evidence_tool_call_id is None:
        raise PulseOutcomeConflict("Outcome readout requires evidence or a failure classification.")
    try:
        evidence = load_measurement_evidence(
            team_id=input.team_id, run_id=input.run_id, tool_call_id=readout.evidence_tool_call_id
        )
    except PulseOutcomeConflict:
        return _failed_measurement(plan=plan, run_id=input.run_id, failure_code="evidence_unavailable", now=input.now)
    try:
        evidence_set = _measurement_evidence_set(
            team_id=input.team_id,
            run_id=input.run_id,
            tool_call_id=readout.evidence_tool_call_id,
        )
    except PulseOutcomeConflict:
        return _failed_measurement(plan=plan, run_id=input.run_id, failure_code="evidence_unavailable", now=input.now)
    evaluation = evaluate_measurement(plan=plan, evidence=evidence)
    if evaluation.status == "inconclusive":
        return _failed_measurement(
            plan=plan,
            run_id=input.run_id,
            failure_code=evaluation.failure_code or "measurement_inconclusive",
            now=input.now,
            evidence_set=evidence_set,
        )
    observation = OutcomeObservation.objects.for_team(input.team_id).create(
        team_id=input.team_id,
        plan=plan,
        run_id=input.run_id,
        attempt_number=plan.attempt_count + 1,
        status=OutcomeObservation.Status.MEASURED,
        observed_value=evaluation.observed_value,
        observed_from=evaluation.observed_from,
        observed_to=evaluation.observed_to,
        absolute_delta=evaluation.absolute_delta,
        relative_delta=evaluation.relative_delta,
        verdict=evaluation.verdict,
        evidence_set=evidence_set,
    )
    plan.attempt_count += 1
    plan.readout_status = OutcomePlan.ReadoutStatus.MEASURED
    plan.completed_at = input.now
    plan.claimed_by_run_id = None
    plan.claimed_at = None
    plan.last_failure_code = None
    plan.save(
        update_fields=[
            "attempt_count",
            "readout_status",
            "completed_at",
            "claimed_by_run",
            "claimed_at",
            "last_failure_code",
            "updated_at",
        ]
    )
    transaction.on_commit(
        lambda: capture_pulse_outcome(
            team_id=plan.team_id,
            run_id=input.run_id,
            event="pulse_outcome_attempted",
            plan_id=plan.id,
            status="measured",
            verdict=evaluation.verdict,
        )
    )
    return _observation_dto(observation)


def _failed_measurement(
    *,
    plan: OutcomePlan,
    run_id: UUID,
    failure_code: str,
    now: datetime,
    evidence_set: EvidenceSet | None = None,
) -> OutcomeObservationDTO:
    next_attempt = plan.attempt_count + 1
    terminal = next_attempt >= _bounded_setting("PULSE_OUTCOME_MAX_ATTEMPTS", _MAX_ATTEMPTS, _MAX_ATTEMPTS)
    observation = OutcomeObservation.objects.for_team(plan.team_id).create(
        team_id=plan.team_id,
        plan=plan,
        run_id=run_id,
        attempt_number=next_attempt,
        status=OutcomeObservation.Status.INCONCLUSIVE if terminal else OutcomeObservation.Status.FAILED,
        verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
        failure_code=failure_code,
        evidence_set=evidence_set,
    )
    plan.attempt_count = next_attempt
    plan.readout_status = OutcomePlan.ReadoutStatus.INCONCLUSIVE if terminal else OutcomePlan.ReadoutStatus.DUE
    plan.next_readout_at = None if terminal else now + _NOT_READY_RETRY_DELAY
    plan.completed_at = now if terminal else None
    plan.claimed_by_run_id = None
    plan.claimed_at = None
    plan.last_failure_code = failure_code
    plan.save(
        update_fields=[
            "attempt_count",
            "readout_status",
            "next_readout_at",
            "completed_at",
            "claimed_by_run",
            "claimed_at",
            "last_failure_code",
            "updated_at",
        ]
    )
    transaction.on_commit(
        lambda: capture_pulse_outcome(
            team_id=plan.team_id,
            run_id=run_id,
            event="pulse_outcome_attempted",
            plan_id=plan.id,
            status="inconclusive" if terminal else "failed",
            reason=failure_code if failure_code in {"evidence_unavailable", "measurement_inconclusive"} else None,
        )
    )
    return _observation_dto(observation)


def _terminal_inconclusive(
    *, plan: OutcomePlan, run_id: UUID, failure_code: str, now: datetime
) -> OutcomeObservationDTO:
    observation = OutcomeObservation.objects.for_team(plan.team_id).create(
        team_id=plan.team_id,
        plan=plan,
        run_id=run_id,
        attempt_number=plan.attempt_count + 1,
        status=OutcomeObservation.Status.INCONCLUSIVE,
        verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
        failure_code=failure_code,
    )
    plan.attempt_count += 1
    plan.readout_status = OutcomePlan.ReadoutStatus.INCONCLUSIVE
    plan.completed_at = now
    plan.claimed_by_run_id = None
    plan.claimed_at = None
    plan.last_failure_code = failure_code
    plan.save(
        update_fields=[
            "attempt_count",
            "readout_status",
            "completed_at",
            "claimed_by_run",
            "claimed_at",
            "last_failure_code",
            "updated_at",
        ]
    )
    transaction.on_commit(
        lambda: capture_pulse_outcome(
            team_id=plan.team_id,
            run_id=run_id,
            event="pulse_outcome_attempted",
            plan_id=plan.id,
            status="inconclusive",
            verdict="inconclusive",
            reason="not_ready_expired" if failure_code == "not_ready_expired" else None,
        )
    )
    return _observation_dto(observation)


def load_measurement_evidence(*, team_id: int, run_id: UUID, tool_call_id: str) -> MeasurementEvidence:
    try:
        call = (
            EvidenceToolCall.objects.for_team(team_id)
            .select_related("raw_body")
            .get(run_id=run_id, tool_call_id=tool_call_id, completed_at__isnull=False)
        )
        body = EvidenceRawBody.objects.for_team(team_id).get(tool_call=call)
    except (EvidenceToolCall.DoesNotExist, EvidenceRawBody.DoesNotExist) as error:
        raise PulseOutcomeConflict("Outcome evidence body is unavailable.") from error
    if call.purged_at is not None or call.raw_expires_at is None or call.raw_expires_at <= timezone.now():
        raise PulseOutcomeConflict("Outcome evidence body is unavailable.")
    try:
        arguments = json.loads(body.encrypted_arguments or "")
        result = json.loads(body.encrypted_result or "") if body.encrypted_result is not None else None
    except (TypeError, ValueError) as error:
        raise PulseOutcomeConflict("Outcome evidence body is invalid.") from error
    if not isinstance(arguments, dict):
        raise PulseOutcomeConflict("Outcome evidence arguments are invalid.")
    return MeasurementEvidence(
        run_id=run_id,
        tool_call_id=call.tool_call_id,
        tool_name=call.tool_name,
        tool_schema_version=call.tool_schema_version,
        arguments=cast(dict[str, object], arguments),
        result=result,
        completed_at=call.completed_at,
        error_class=call.error_class,
        result_truncated=call.result_truncated,
    )


def _measurement_evidence_set(*, team_id: int, run_id: UUID, tool_call_id: str) -> EvidenceSet:
    try:
        call = EvidenceToolCall.objects.for_team(team_id).get(
            run_id=run_id,
            tool_call_id=tool_call_id,
            completed_at__isnull=False,
        )
    except EvidenceToolCall.DoesNotExist as error:
        raise PulseOutcomeConflict("Outcome evidence provenance is unavailable.") from error
    completed_at = call.completed_at
    if (
        completed_at is None
        or not call.normalized_result_ref.startswith("sha256:")
        or len(call.normalized_result_ref) != 71
        or any(character not in "0123456789abcdef" for character in call.normalized_result_ref[7:])
    ):
        raise PulseOutcomeConflict("Outcome evidence provenance is invalid.")
    refs = [
        {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "tool_schema_version": call.tool_schema_version,
            "completed_at": completed_at.isoformat(),
            "result_hash": call.normalized_result_ref,
        }
    ]
    content_hash = sha256(json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    evidence_set, _ = EvidenceSet.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        run_id=run_id,
        content_hash=content_hash,
        defaults={"item_refs": refs},
    )
    if evidence_set.item_refs != refs:
        raise PulseOutcomeConflict("Outcome evidence provenance retry conflicts.")
    return evidence_set


def _observation_dto(observation: OutcomeObservation) -> OutcomeObservationDTO:
    return OutcomeObservationDTO(
        id=observation.id,
        plan_id=observation.plan_id,
        attempt_number=observation.attempt_number,
        status=cast(Literal["measured", "inconclusive", "failed"], observation.status),
        verdict=cast(Literal["improved", "flat", "regressed", "inconclusive"], observation.verdict),
    )


def _bounded_setting(name: str, default: int, cap: int) -> int:
    value = getattr(settings, name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return default
    return min(value, cap)
