"""Temporal activities backing the foundry-build-bet workflow's gate-awaiting poll loop.

The gauntlet itself is unchanged (``foundry-run-gate``, triggered the exact same way it
always has been — the automatic hook off an ``artifact.ready`` event while building, see
``logic/gate.py``). These activities only answer "has a *new* gate.result landed for this
bet since I emitted my artifact?" so the build workflow can poll for it with short,
restart-safe activity calls instead of either blocking in one long-running activity or
growing a new signal-based coupling between the event-apply path and this workflow.

Correlation is by position, not wall-clock time: ``count_gate_results_activity`` takes a
baseline count of this bet's gate.result events right before a builder attempt runs, and
``check_gate_result_activity`` looks only at events past that baseline. This sidesteps
comparing Temporal's (skippable, in tests) workflow clock against Django's real
``created_at`` timestamps, and doubles as the "dedupe by event id" the double-gate.result
quirk calls for: a stray degenerate result from an earlier attempt's trigger is already
behind the baseline and never considered "new" for a later attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from posthog.temporal.common.utils import asyncify


@dataclass
class CountGateResultsInput:
    bet_id: str
    team_id: int


@activity.defn
@asyncify
def count_gate_results_activity(input: CountGateResultsInput) -> int:
    from products.foundry.backend.facade import api as foundry_api  # noqa: PLC0415
    from products.foundry.backend.facade.enums import BetEventKind  # noqa: PLC0415

    return sum(
        1 for event in foundry_api.list_events(input.team_id, input.bet_id) if event.kind == BetEventKind.GATE_RESULT
    )


@dataclass
class CheckGateResultInput:
    bet_id: str
    team_id: int
    known_count: int


@dataclass
class GateResultSnapshot:
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)


@activity.defn
@asyncify
def check_gate_result_activity(input: CheckGateResultInput) -> GateResultSnapshot | None:
    """One poll attempt: is there a gate.result for this bet past ``known_count``?

    If more than one landed (the double-gate.result quirk), prefer any ``pass: true``
    result over the rest, else take the most recent — ``list_events`` already orders by
    ``created_at``.
    """
    from products.foundry.backend.facade import api as foundry_api  # noqa: PLC0415
    from products.foundry.backend.facade.enums import BetEventKind  # noqa: PLC0415

    gate_results = [
        event
        for event in foundry_api.list_events(input.team_id, input.bet_id)
        if event.kind == BetEventKind.GATE_RESULT
    ]
    new_results = gate_results[input.known_count :]
    if not new_results:
        return None

    passing = [event for event in new_results if event.payload.get("pass") is True]
    chosen = passing[-1] if passing else new_results[-1]
    return GateResultSnapshot(
        passed=bool(chosen.payload.get("pass")),
        checks=list(chosen.payload.get("checks") or []),
        violations=list(chosen.payload.get("violations") or []),
    )
