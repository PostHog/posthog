"""Bounded, subscription-local outcome memory for future Pulse analyses."""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from django.conf import settings
from django.utils import timezone

from posthog.dataclasses import frozen

from products.subscriptions.backend.models import OutcomeObservation, OutcomePlan

from .contracts import OutcomeMemoryBucketDTO, OutcomeMemoryDTO, OutcomeMemoryProposalDTO

OUTCOME_MEMORY_VERSION = 1
OUTCOME_SUPPRESSION_WINDOW = timedelta(days=90)
DEFAULT_OUTCOME_MEMORY_MAX_ROWS = 50
MAX_OUTCOME_MEMORY_ROWS = 100
DEFAULT_OUTCOME_MEMORY_MAX_BYTES = 16 * 1024
MAX_OUTCOME_MEMORY_BYTES = 32 * 1024
_ACTIVE_READOUT_STATUSES = frozenset(
    {
        OutcomePlan.ReadoutStatus.WAITING,
        OutcomePlan.ReadoutStatus.SCHEDULED,
        OutcomePlan.ReadoutStatus.DUE,
        OutcomePlan.ReadoutStatus.MEASURING,
    }
)


@frozen
class _OutcomeObservationSnapshot:
    status: str
    verdict: str


def build_outcome_memory(*, team_id: int, subscription_id: int, now: datetime | None = None) -> OutcomeMemoryDTO:
    """Return privacy-bounded proposal history for one subscription, never raw evidence."""
    current_time = now or timezone.now()
    row_cap = _bounded_setting(
        "PULSE_OUTCOME_MEMORY_MAX_ROWS", default=DEFAULT_OUTCOME_MEMORY_MAX_ROWS, cap=MAX_OUTCOME_MEMORY_ROWS
    )
    configured_byte_cap = _bounded_setting(
        "PULSE_OUTCOME_MEMORY_MAX_BYTES", default=DEFAULT_OUTCOME_MEMORY_MAX_BYTES, cap=MAX_OUTCOME_MEMORY_BYTES
    )
    plans = list(
        OutcomePlan.objects.for_team(team_id)
        .filter(subscription_id=subscription_id)
        .select_related("proposal__opportunity", "source_action")
        .order_by("-updated_at", "-created_at")[: row_cap + 1]
    )
    latest_observations = _latest_observations(team_id=team_id, plan_ids=[plan.id for plan in plans])
    latest_verdicts = {plan_id: observation.verdict for plan_id, observation in latest_observations.items()}
    buckets = _buckets(plans=plans, latest_observations=latest_observations)
    eligible = [
        _proposal_dto(plan=plan, verdict=latest_verdicts.get(plan.id))
        for plan in plans
        if _is_memory_eligible(plan=plan, now=current_time)
    ]

    minimum_memory_bytes = max(
        _encoded_bytes(
            OutcomeMemoryDTO(
                version=OUTCOME_MEMORY_VERSION, proposals=(), buckets=(), rows_considered=len(plans), truncated=False
            )
        ),
        _encoded_bytes(
            OutcomeMemoryDTO(
                version=OUTCOME_MEMORY_VERSION, proposals=(), buckets=(), rows_considered=len(plans), truncated=True
            )
        ),
    )
    byte_cap = configured_byte_cap if configured_byte_cap >= minimum_memory_bytes else DEFAULT_OUTCOME_MEMORY_MAX_BYTES
    truncated = len(plans) > row_cap or len(eligible) > row_cap
    retained: list[OutcomeMemoryProposalDTO] = []
    bounded_buckets = buckets
    if (
        _encoded_bytes(
            OutcomeMemoryDTO(
                version=OUTCOME_MEMORY_VERSION,
                proposals=(),
                buckets=bounded_buckets,
                rows_considered=len(plans),
                truncated=truncated,
            )
        )
        > byte_cap
    ):
        bounded_buckets = ()
        truncated = True
    for proposal in eligible[:row_cap]:
        candidate = (*retained, proposal)
        memory = OutcomeMemoryDTO(
            version=OUTCOME_MEMORY_VERSION,
            proposals=candidate,
            buckets=bounded_buckets,
            rows_considered=len(plans),
            truncated=truncated,
        )
        if _encoded_bytes(memory) > byte_cap:
            truncated = True
            break
        retained.append(proposal)
    if len(retained) < len(eligible):
        truncated = True
    memory = OutcomeMemoryDTO(
        version=OUTCOME_MEMORY_VERSION,
        proposals=tuple(retained),
        buckets=bounded_buckets,
        rows_considered=len(plans),
        truncated=truncated,
    )
    while _encoded_bytes(memory) > byte_cap:
        if retained:
            retained.pop()
        elif bounded_buckets:
            bounded_buckets = ()
        else:
            raise RuntimeError("Outcome memory minimum payload exceeds its effective byte cap.")
        memory = OutcomeMemoryDTO(
            version=OUTCOME_MEMORY_VERSION,
            proposals=tuple(retained),
            buckets=bounded_buckets,
            rows_considered=len(plans),
            truncated=True,
        )
    return memory


def _latest_observations(*, team_id: int, plan_ids: list[object]) -> dict[object, _OutcomeObservationSnapshot]:
    observations_by_plan: dict[object, _OutcomeObservationSnapshot] = {}
    if not plan_ids:
        return observations_by_plan
    observations = (
        OutcomeObservation.objects.for_team(team_id)
        .filter(plan_id__in=plan_ids)
        .order_by("plan_id", "-created_at")
        .distinct("plan_id")
        .only("plan_id", "status", "verdict")
    )
    for observation in observations:
        observations_by_plan.setdefault(
            observation.plan_id,
            _OutcomeObservationSnapshot(
                status=cast(str, observation.status),
                verdict=cast(str, observation.verdict),
            ),
        )
    return observations_by_plan


def _proposal_dto(*, plan: OutcomePlan, verdict: str | None) -> OutcomeMemoryProposalDTO:
    proposal = plan.proposal
    target = proposal.normalized_target
    category = "other"
    if isinstance(target, dict):
        for key in ("category", "kind", "area"):
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                category = value.strip()[:120]
                break
    metric_name = plan.source_action.metric_name or ""
    terminal_at = _terminal_at(plan)
    return OutcomeMemoryProposalDTO(
        opportunity_key=proposal.opportunity.stable_key,
        action_key=proposal.stable_action_key,
        kind=proposal.kind,
        target_category=category,
        metric_name=metric_name[:255],
        adoption_status=plan.adoption_status,
        readout_status=plan.readout_status,
        adoption_source=plan.adoption_source,
        verdict=verdict,
        last_seen_at=proposal.last_seen_at,
        terminal_at=terminal_at,
    )


def _is_memory_eligible(*, plan: OutcomePlan, now: datetime) -> bool:
    if plan.readout_status in _ACTIVE_READOUT_STATUSES:
        return True
    terminal_at = _terminal_at(plan)
    return terminal_at is not None and terminal_at >= now - OUTCOME_SUPPRESSION_WINDOW


def _terminal_at(plan: OutcomePlan) -> datetime | None:
    if plan.readout_status in _ACTIVE_READOUT_STATUSES:
        return None
    return plan.completed_at or plan.updated_at


def _buckets(
    *, plans: list[OutcomePlan], latest_observations: dict[object, _OutcomeObservationSnapshot]
) -> tuple[OutcomeMemoryBucketDTO, ...]:
    totals: dict[tuple[str, str], list[int]] = {}
    for plan in plans:
        observation = latest_observations.get(plan.id)
        proposal = _proposal_dto(plan=plan, verdict=observation.verdict if observation is not None else None)
        values = totals.setdefault((proposal.kind, proposal.target_category), [0, 0, 0, 0, 0])
        values[0] += 1
        values[1] += int(plan.adoption_status == OutcomePlan.AdoptionStatus.ADOPTED)
        measured = observation is not None and observation.status == OutcomeObservation.Status.MEASURED
        values[2] += int(measured)
        values[3] += int(observation is not None and observation.status == OutcomeObservation.Status.INCONCLUSIVE)
        values[4] += int(
            measured and observation is not None and observation.verdict == OutcomeObservation.Verdict.IMPROVED
        )
    return tuple(
        OutcomeMemoryBucketDTO(
            kind=kind,
            target_category=category,
            total=total,
            adopted=adopted,
            measured=measured,
            inconclusive=inconclusive,
            improved=improved,
            adoption_rate=Decimal(adopted) / Decimal(total) if total else None,
            improvement_rate=Decimal(improved) / Decimal(measured) if measured else None,
        )
        for (kind, category), (total, adopted, measured, inconclusive, improved) in sorted(totals.items())
    )


def _encoded_bytes(memory: OutcomeMemoryDTO) -> int:
    return len(json.dumps(asdict(memory), default=_json_default, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported outcome-memory value: {type(value).__name__}")


def _bounded_setting(name: str, *, default: int, cap: int) -> int:
    value = getattr(settings, name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return default
    return min(value, cap)
