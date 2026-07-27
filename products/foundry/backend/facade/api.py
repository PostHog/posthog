"""
Facade for foundry.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

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


def _to_dto(bet: Bet) -> contracts.BetDTO:
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
        feature_flag_id=bet.feature_flag_id,
        feature_flag_key=bet.feature_flag.key if bet.feature_flag_id else None,
        experiment_id=bet.experiment_id,
        created_by_id=bet.created_by_id,
        created_at=bet.created_at,
        updated_at=bet.updated_at,
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
        return Bet.objects.select_related("feature_flag").get(team_id=team_id, id=bet_id)
    except Bet.DoesNotExist:
        raise BetNotFound(f"bet {bet_id} does not exist in this project")


def create_bet(input: contracts.CreateBetInput, *, user: User | None = None) -> contracts.BetDTO:
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
    )
    return _to_dto(bet)


def get_bet(team_id: int, bet_id: UUID | str) -> contracts.BetDTO:
    return _to_dto(_get_bet(team_id, bet_id))


def list_bets(team_id: int) -> list[contracts.BetDTO]:
    return [
        _to_dto(bet)
        for bet in Bet.objects.select_related("feature_flag").filter(team_id=team_id).order_by("-created_at")
    ]


def fund_bet(
    team_id: int,
    bet_id: UUID | str,
    *,
    user: User | None = None,
    serializer_context: dict | None = None,
) -> contracts.BetDTO:
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
    event = logic.apply_event(_get_bet(team_id, bet_id), kind, payload, user)
    return _to_event_dto(event)


def record_verdict(
    team_id: int,
    bet_id: UUID | str,
    verdict: BetVerdict,
    *,
    user: User | None = None,
) -> contracts.BetDTO:
    bet = logic.record_verdict(_get_bet(team_id, bet_id), verdict, user)
    return _to_dto(bet)


def list_events(team_id: int, bet_id: UUID | str) -> list[contracts.BetEventDTO]:
    bet = _get_bet(team_id, bet_id)
    return [_to_event_dto(event) for event in bet.events.all()]


def list_nodes(team_id: int, bet_id: UUID | str) -> list[contracts.BetNodeDTO]:
    bet = _get_bet(team_id, bet_id)
    return [_to_node_dto(node) for node in bet.nodes.all()]
