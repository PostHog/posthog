"""Business logic for foundry: the Bet state machine and its side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from products.experiments.backend.facade import CreateExperimentInput, create_experiment

from ..facade.enums import BetEventKind, BetState, BetVerdict, ExecutionMode
from ..models import Bet, BetEvent

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


class BetStateError(Exception):
    """Raised when an action is not valid for the bet's current state."""


VALID_TRANSITIONS: dict[BetState, frozenset[BetState]] = {
    BetState.DRAFTED: frozenset({BetState.FUNDED}),
    BetState.FUNDED: frozenset({BetState.BUILDING}),
    BetState.BUILDING: frozenset({BetState.GATED}),
    BetState.GATED: frozenset({BetState.EXPOSED}),
    BetState.EXPOSED: frozenset({BetState.BUILDING, BetState.ARCHIVED}),
    BetState.ARCHIVED: frozenset(),
}


def _record_event(
    bet: Bet,
    kind: BetEventKind,
    payload: dict[str, Any],
    user: User | None,
) -> BetEvent:
    return BetEvent.objects.create(
        team_id=bet.team_id,
        bet=bet,
        kind=kind,
        payload=payload,
        created_by=user,
    )


def _transition(bet: Bet, to_state: BetState, user: User | None, detail: dict[str, Any] | None = None) -> None:
    from_state = BetState(bet.state)
    if to_state not in VALID_TRANSITIONS[from_state]:
        raise BetStateError(f"cannot move a bet from '{from_state}' to '{to_state}'")
    bet.state = to_state
    bet.save(update_fields=["state", "updated_at"])
    _record_event(bet, BetEventKind.STATE_CHANGED, {"from": from_state, "to": to_state, **(detail or {})}, user)


def create_bet(
    *,
    team: Team,
    user: User | None,
    slug: str,
    hypothesis: str,
    success_metric: dict[str, Any],
    guardrails: list[dict[str, Any]],
    budget: dict[str, Any],
    exposure_plan: dict[str, Any],
    sources: list[dict[str, Any]],
    ttl: Any = None,
    execution_mode: ExecutionMode = ExecutionMode.EXTERNAL,
    run_config: dict[str, Any] | None = None,
    memory_repo_url: str | None = None,
) -> Bet:
    return Bet.objects.create(
        team=team,
        created_by=user,
        slug=slug,
        hypothesis=hypothesis,
        success_metric=success_metric,
        guardrails=guardrails,
        budget=budget,
        exposure_plan=exposure_plan,
        sources=sources,
        ttl=ttl,
        execution_mode=execution_mode,
        run_config=run_config or {},
        memory_repo_url=memory_repo_url,
    )


def fund_bet(bet: Bet, user: User | None, serializer_context: dict | None = None) -> Bet:
    """Fund a drafted bet: create its feature flag + draft experiment, move to funded.

    The experiments facade creates both objects atomically (the flag stays
    inactive while the experiment is a draft). Deliberately not wrapped in an
    outer transaction: gated flag writes may raise ApprovalRequired, which
    must not be swallowed by a rollback of our own state.
    """
    if BetState(bet.state) != BetState.DRAFTED:
        raise BetStateError(f"only drafted bets can be funded (bet is '{bet.state}')")

    experiment = create_experiment(
        team=bet.team,
        user=user,
        input_dto=CreateExperimentInput(
            name=f"Bet: {bet.slug}",
            description=bet.hypothesis,
            feature_flag_key=f"bet-{bet.slug}",
            start_date=None,
            metrics=[],
            serializer_context=serializer_context,
        ),
    )
    bet.experiment_id = experiment.id
    bet.feature_flag_id = experiment.feature_flag_id
    bet.save(update_fields=["experiment", "feature_flag", "updated_at"])
    _transition(
        bet,
        BetState.FUNDED,
        user,
        {"feature_flag_id": experiment.feature_flag_id, "experiment_id": experiment.id},
    )
    return bet


def apply_event(bet: Bet, kind: BetEventKind, payload: dict[str, Any], user: User | None) -> BetEvent:
    """Append an orchestrator event and drive any state transition it implies."""
    state = BetState(bet.state)
    if state == BetState.ARCHIVED:
        raise BetStateError("archived bets are immutable")
    if kind == BetEventKind.STATE_CHANGED:
        raise BetStateError("state.changed events are system-emitted and cannot be posted")
    if kind == BetEventKind.GATE_RESULT and state != BetState.BUILDING:
        raise BetStateError(f"gate.result is only valid while building (bet is '{state}')")
    if kind == BetEventKind.EXPOSURE_STARTED and state != BetState.GATED:
        raise BetStateError(f"exposure.started is only valid once gated (bet is '{state}')")

    with transaction.atomic():
        event = _record_event(bet, kind, payload, user)
        if kind == BetEventKind.RUN_STARTED and state == BetState.FUNDED:
            _transition(bet, BetState.BUILDING, user)
        elif kind == BetEventKind.GATE_RESULT and payload.get("pass") is True:
            _transition(bet, BetState.GATED, user)
        elif kind == BetEventKind.EXPOSURE_STARTED:
            _transition(bet, BetState.EXPOSED, user)
    return event


def record_verdict(bet: Bet, verdict: BetVerdict, user: User | None) -> Bet:
    """Resolve an exposed bet: promote/roll back archives it, iterate loops it."""
    if BetState(bet.state) != BetState.EXPOSED:
        raise BetStateError(f"only exposed bets can receive a verdict (bet is '{bet.state}')")

    with transaction.atomic():
        if verdict == BetVerdict.ITERATE:
            bet.iteration += 1
            bet.save(update_fields=["iteration", "updated_at"])
            _transition(bet, BetState.BUILDING, user, {"verdict": verdict, "iteration": bet.iteration})
        else:
            bet.verdict = verdict
            bet.save(update_fields=["verdict", "updated_at"])
            _transition(bet, BetState.ARCHIVED, user, {"verdict": verdict})
    return bet
