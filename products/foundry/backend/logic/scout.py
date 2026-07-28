"""The scout: guardrail evaluation and verdict-proposal conditions.

Two callers share this module: the exposure workflow's per-step breach check (via
``temporal/expose_activities.py``) and the periodic sweep (``tasks/tasks.py::
foundry_scout_task``). Guardrail evaluation reuses the same synchronous read surface
every other non-UI metric consumer in this codebase already imports directly —
``posthog.caching.calculate_for_query_based_insight`` (see e.g.
``products/alerts/backend/evaluation/trends.py``, ``products/pulse/backend/sources/
strategy.py``) — there is no dedicated "insights" product facade to route through
instead. No new metric engine: a guardrail's evaluated value is read off an existing
insight's result and compared to a threshold, exactly like a gate check compares a
coverage percentage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight

from products.experiments.backend.facade import api as experiments_api
from products.product_analytics.backend.models.insight import Insight

from ..facade.enums import BetEventKind, BetState, BetVerdict
from ..models import Bet, BetEvent

logger = logging.getLogger(__name__)

# How far back the scout looks when reading a guardrail's insight, and how long an
# exposure must sit fully rolled out with no halt before "exposure completed" counts as
# decided enough to propose a verdict. Deliberately small so the ADR-6 dev-stack E2E
# (a short-min_hours ramp) can observe a proposal without waiting hours — a production
# deployment would likely want both larger; documented here rather than re-derived
# per call.
GUARDRAIL_LOOKBACK_HOURS = 24.0
EXPOSURE_STABILITY_HOURS = 0.05  # ~3 minutes


@dataclass(frozen=True)
class GuardrailEvaluation:
    name: str
    parameterized: bool
    breached: bool
    detail: str


def _extract_scalar(result: Any) -> float | None:
    """Best-effort reduction of an insight's raw result payload to one comparable
    number: a trend series' last data point, or a bare aggregated_value/numeric result.
    A shape this can't reduce is treated as unparameterized rather than crashing the
    scout sweep — same tone as ``gauntlet.py``'s ``flag_guard_check_outcome``: a fast
    tripwire, not a proof."""
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            if "aggregated_value" in first:
                try:
                    return float(first["aggregated_value"])
                except (TypeError, ValueError):
                    return None
            data = first.get("data")
            if isinstance(data, list) and data:
                try:
                    return float(data[-1])
                except (TypeError, ValueError):
                    return None
        return None
    if isinstance(result, int | float):
        return float(result)
    return None


def evaluate_guardrail(
    bet: Bet, guardrail: dict[str, Any], *, lookback_hours: float = GUARDRAIL_LOOKBACK_HOURS
) -> GuardrailEvaluation:
    """Evaluate one guardrail's machine-checkable params against a lookback window.

    An unparameterized guardrail (missing ``metric.query_ref``/``threshold``/
    ``direction``) is skipped, not failed — see ADR-6 decision 3.
    """
    name = str(guardrail.get("name") or "guardrail")
    metric = guardrail.get("metric") or {}
    query_ref = metric.get("query_ref")
    threshold = guardrail.get("threshold")
    direction = guardrail.get("direction")
    if not query_ref or threshold is None or not direction:
        return GuardrailEvaluation(name=name, parameterized=False, breached=False, detail="not parameterized, skipped")

    try:
        insight = Insight.objects.get(team_id=bet.team_id, short_id=query_ref)
    except Insight.DoesNotExist:
        return GuardrailEvaluation(
            name=name, parameterized=True, breached=False, detail=f"insight '{query_ref}' not found"
        )

    try:
        result = calculate_for_query_based_insight(
            insight,
            team=bet.team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
            filters_override={"date_from": f"-{lookback_hours:g}h"},
        )
    except Exception as e:
        logger.exception("foundry-scout: guardrail query failed", extra={"bet_id": str(bet.id), "guardrail": name})
        return GuardrailEvaluation(name=name, parameterized=True, breached=False, detail=f"query failed: {e}")

    value = _extract_scalar(result.result)
    if value is None:
        return GuardrailEvaluation(
            name=name, parameterized=True, breached=False, detail="could not read a comparable value from the insight"
        )

    breached = value > threshold if direction == "above" else value < threshold
    return GuardrailEvaluation(
        name=name,
        parameterized=True,
        breached=breached,
        detail=f"{value:.4g} vs threshold {threshold:g} ({direction}, lookback {lookback_hours:g}h)",
    )


def evaluate_guardrails(bet: Bet, *, lookback_hours: float = GUARDRAIL_LOOKBACK_HOURS) -> list[GuardrailEvaluation]:
    return [evaluate_guardrail(bet, guardrail, lookback_hours=lookback_hours) for guardrail in bet.guardrails or []]


@dataclass(frozen=True)
class VerdictProposal:
    condition: str
    recommendation: BetVerdict
    evidence: dict[str, Any]


def _existing_conditions(bet: Bet) -> set[str]:
    # .for_team(), not the bare default manager: this runs from the beat-scheduled sweep
    # (tasks/tasks.py::foundry_scout_task), which has no ambient team_scope() context —
    # BetEvent is fail-closed (TeamScopedRootMixin) and raises without one.
    return {
        event.payload.get("evidence", {}).get("condition")
        for event in BetEvent.objects.for_team(bet.team_id).filter(bet=bet, kind=BetEventKind.VERDICT_PROPOSED)
    }


def _exposure_progress(bet: Bet) -> tuple[int, int, Any]:
    """(steps_advanced, total_steps, last_advance_at) derived from exposure_plan + the
    exposure.advanced event log."""
    steps = list((bet.exposure_plan or {}).get("steps") or [])
    advanced = list(
        BetEvent.objects.for_team(bet.team_id)
        .filter(bet=bet, kind=BetEventKind.EXPOSURE_ADVANCED)
        .order_by("created_at")
    )
    last_at = advanced[-1].created_at if advanced else None
    return len(advanced), len(steps), last_at


def propose_verdicts_for_bet(bet: Bet) -> list[VerdictProposal]:
    """Evaluate every conclusion condition for one exposed bet and return the proposals
    that haven't already been made. Dedup is against the bet's own ``verdict.proposed``
    event log — one proposal per condition, ever (ADR-6 decision 4). Pure decision logic:
    the caller (``tasks/tasks.py::foundry_scout_task``) records the returned proposals as
    events.

    Recommendation rules per condition (documented, not just implied):
    - guardrail breached now -> rolled_back (safety signal, regardless of experiment state).
    - experiment significant -> promoted (a documented simplification: this integration
      depth reads only the raw ExperimentQueryRunner's boolean `significant` flag, not a
      normalized delta sign — a real follow-up, same honesty standard as this product's
      other stated heuristics, e.g. gauntlet.py's flag_guard).
    - TTL reached -> iterate, unless the bet already halted once (exposure.halted present)
      -> rolled_back (a bet that already tripped a guardrail shouldn't get another loop
      by default).
    - exposure plan fully advanced, no halt, stable for EXPOSURE_STABILITY_HOURS -> promoted.
    """
    if BetState(bet.state) != BetState.EXPOSED:
        return []
    existing = _existing_conditions(bet)
    proposals: list[VerdictProposal] = []

    halted = BetEvent.objects.for_team(bet.team_id).filter(bet=bet, kind=BetEventKind.EXPOSURE_HALTED).exists()
    breached = [g for g in evaluate_guardrails(bet) if g.parameterized and g.breached]
    if breached and "guardrail_breach" not in existing:
        proposals.append(
            VerdictProposal(
                condition="guardrail_breach",
                recommendation=BetVerdict.ROLLED_BACK,
                evidence={
                    "condition": "guardrail_breach",
                    "guardrails": [{"name": g.name, "detail": g.detail} for g in breached],
                },
            )
        )

    if bet.experiment_id is not None and "experiment_significant" not in existing:
        significance = experiments_api.get_experiment_significance(team=bet.team, experiment_id=bet.experiment_id)
        if significance is not None and significance.any_significant:
            proposals.append(
                VerdictProposal(
                    condition="experiment_significant",
                    recommendation=BetVerdict.PROMOTED,
                    evidence={
                        "condition": "experiment_significant",
                        "metrics_evaluated": significance.metrics_evaluated,
                        "variants": [{"key": v.key, "significant": v.significant} for v in significance.variants],
                    },
                )
            )

    if bet.ttl is not None and timezone.now() >= bet.ttl and "ttl_reached" not in existing:
        proposals.append(
            VerdictProposal(
                condition="ttl_reached",
                recommendation=BetVerdict.ROLLED_BACK if halted else BetVerdict.ITERATE,
                evidence={"condition": "ttl_reached", "ttl": bet.ttl.isoformat(), "halted": halted},
            )
        )

    advanced, total, last_at = _exposure_progress(bet)
    if (
        total > 0
        and advanced >= total
        and not halted
        and last_at is not None
        and timezone.now() >= last_at + timedelta(hours=EXPOSURE_STABILITY_HOURS)
        and "exposure_completed" not in existing
    ):
        proposals.append(
            VerdictProposal(
                condition="exposure_completed",
                recommendation=BetVerdict.PROMOTED,
                evidence={
                    "condition": "exposure_completed",
                    "steps_completed": advanced,
                    "stable_since": last_at.isoformat(),
                },
            )
        )

    return proposals
