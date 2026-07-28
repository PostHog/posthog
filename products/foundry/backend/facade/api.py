"""
Facade for foundry.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from .. import logic
from ..models import Bet, BetEvent, BetNode
from . import contracts
from .enums import BetEventKind, BetState, BetVerdict, ExecutionMode, NodeStatus

if TYPE_CHECKING:
    from posthog.models.user import User

BetStateError = logic.BetStateError


class BetNotFound(Exception):
    pass


def _to_dto(bet: Bet, *, exposure_advanced_steps: int = 0, exposure_halted: bool = False) -> contracts.BetDTO:
    return contracts.BetDTO(
        id=bet.id,
        slug=bet.slug,
        hypothesis=bet.hypothesis,
        success_metric=bet.success_metric,
        guardrails=bet.guardrails,
        budget=bet.budget,
        exposure_plan=bet.exposure_plan,
        sources=bet.sources,
        ttl=bet.ttl,
        state=BetState(bet.state),
        verdict=BetVerdict(bet.verdict) if bet.verdict else None,
        iteration=bet.iteration,
        execution_mode=ExecutionMode(bet.execution_mode),
        run_config=bet.run_config,
        memory_repo_url=bet.memory_repo_url,
        gate_config=bet.gate_config,
        feature_flag_id=bet.feature_flag_id,
        feature_flag_key=bet.feature_flag.key if bet.feature_flag else None,
        experiment_id=bet.experiment_id,
        created_by_id=bet.created_by_id,
        created_at=bet.created_at,
        updated_at=bet.updated_at,
        exposure_advanced_steps=exposure_advanced_steps,
        exposure_halted=exposure_halted,
    )


def _exposure_advanced_counts(team_id: int, bet_ids: list) -> dict[Any, int]:
    """One batched COUNT query, not one per bet — used by list_bets so the portfolio
    table's ramp-progress column doesn't pay for an event-log fetch per row.
    ``.for_team()``, not the bare default manager: BetEvent is fail-closed
    (TeamScopedRootMixin) and get_bet/list_bets are called from contexts with no ambient
    team_scope() (e.g. Temporal activities, foundry_attempt_gate_task), not just requests."""
    if not bet_ids:
        return {}
    from django.db.models import Count  # noqa: PLC0415 — only needed for this one aggregate

    rows = (
        BetEvent.objects.for_team(team_id)
        .filter(bet_id__in=bet_ids, kind=BetEventKind.EXPOSURE_ADVANCED)
        .values("bet_id")
        .annotate(count=Count("id"))
    )
    return {row["bet_id"]: row["count"] for row in rows}


def _exposure_halted_bet_ids(team_id: int, bet_ids: list) -> set:
    if not bet_ids:
        return set()
    return set(
        BetEvent.objects.for_team(team_id)
        .filter(bet_id__in=bet_ids, kind=BetEventKind.EXPOSURE_HALTED)
        .values_list("bet_id", flat=True)
        .distinct()
    )


def _to_event_dto(event: BetEvent) -> contracts.BetEventDTO:
    return contracts.BetEventDTO(
        id=event.id,
        bet_id=event.bet_id,
        kind=BetEventKind(event.kind),
        payload=event.payload,
        created_at=event.created_at,
    )


def _to_node_dto(node: BetNode) -> contracts.BetNodeDTO:
    return contracts.BetNodeDTO(
        id=node.id,
        bet_id=node.bet_id,
        parent_id=node.parent_id,
        node_id=node.node_id,
        status=NodeStatus(node.status),
        runner=node.runner,
        depth=node.depth,
        max_cost=float(node.max_cost) if node.max_cost is not None else None,
        max_depth=node.max_depth,
        max_children=node.max_children,
        cost_so_far=float(node.cost_so_far),
        sandbox_external_id=node.sandbox_external_id,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _get_bet(team_id: int, bet_id: UUID | str) -> Bet:
    try:
        return Bet.objects.for_team(team_id).select_related("feature_flag").get(id=bet_id)
    except Bet.DoesNotExist:
        raise BetNotFound(f"bet {bet_id} does not exist in this project")


def create_bet(input: contracts.CreateBetInput, *, user: User | None = None) -> contracts.BetDTO:
    with team_scope(input.team_id):
        bet = logic.create_bet(
            team=Team.objects.get(id=input.team_id),
            user=user,
            slug=input.slug,
            hypothesis=input.hypothesis,
            success_metric=input.success_metric,
            guardrails=input.guardrails,
            budget=input.budget,
            exposure_plan=input.exposure_plan,
            sources=input.sources,
            ttl=input.ttl,
            execution_mode=input.execution_mode,
            run_config=input.run_config,
            memory_repo_url=input.memory_repo_url,
            gate_config=input.gate_config,
        )
        return _to_dto(bet)


def get_bet(team_id: int, bet_id: UUID | str) -> contracts.BetDTO:
    bet = _get_bet(team_id, bet_id)
    return _to_dto(
        bet,
        exposure_advanced_steps=_exposure_advanced_counts(team_id, [bet.id]).get(bet.id, 0),
        exposure_halted=bet.id in _exposure_halted_bet_ids(team_id, [bet.id]),
    )


def list_bets(team_id: int) -> list[contracts.BetDTO]:
    bets = list(Bet.objects.for_team(team_id).select_related("feature_flag").order_by("-created_at"))
    bet_ids = [bet.id for bet in bets]
    advanced_counts = _exposure_advanced_counts(team_id, bet_ids)
    halted_ids = _exposure_halted_bet_ids(team_id, bet_ids)
    return [
        _to_dto(bet, exposure_advanced_steps=advanced_counts.get(bet.id, 0), exposure_halted=bet.id in halted_ids)
        for bet in bets
    ]


def fund_bet(
    team_id: int,
    bet_id: UUID | str,
    *,
    user: User | None = None,
    serializer_context: dict | None = None,
) -> contracts.BetDTO:
    with team_scope(team_id):
        bet = logic.fund_bet(_get_bet(team_id, bet_id), user, serializer_context)
        return _to_dto(bet)


def record_event(
    team_id: int,
    bet_id: UUID | str,
    kind: BetEventKind,
    payload: dict[str, Any],
    *,
    user: User | None = None,
) -> contracts.BetEventDTO:
    with team_scope(team_id):
        event = logic.apply_event(_get_bet(team_id, bet_id), kind, payload, user)
        return _to_event_dto(event)


def record_verdict(
    team_id: int,
    bet_id: UUID | str,
    verdict: BetVerdict,
    *,
    user: User | None = None,
) -> contracts.BetDTO:
    with team_scope(team_id):
        bet = logic.record_verdict(_get_bet(team_id, bet_id), verdict, user)
        return _to_dto(bet)


def list_events(team_id: int, bet_id: UUID | str) -> list[contracts.BetEventDTO]:
    bet = _get_bet(team_id, bet_id)
    return [_to_event_dto(event) for event in BetEvent.objects.for_team(team_id).filter(bet=bet)]


def list_nodes(team_id: int, bet_id: UUID | str) -> list[contracts.BetNodeDTO]:
    bet = _get_bet(team_id, bet_id)
    return [_to_node_dto(node) for node in BetNode.objects.for_team(team_id).filter(bet=bet)]
