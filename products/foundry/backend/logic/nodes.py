"""BetNode tree projection: upserts BetNode rows from node.* / budget.exceeded BetEvents.

BetEvents remain the source of truth (see ``logic/__init__.py::apply_event``); this module
keeps a queryable registry in sync with them so the tree can be rendered without replaying
the whole event log. Runs identically whether the event came from an external orchestrator's
POST or from Foundry's own managed-mode Temporal activities (both go through ``apply_event``).
"""

from __future__ import annotations

from typing import Any

from ..facade.enums import BetEventKind, NodeStatus
from ..models import Bet, BetNode


def upsert_node_from_event(bet: Bet, kind: BetEventKind, payload: dict[str, Any]) -> None:
    if kind == BetEventKind.NODE_SPAWNED:
        _spawn(bet, payload)
    elif kind == BetEventKind.NODE_FINISHED:
        _finish(bet, payload, NodeStatus.FINISHED)
    elif kind == BetEventKind.NODE_FAILED:
        _finish(bet, payload, NodeStatus.FAILED)
    elif kind == BetEventKind.BUDGET_EXCEEDED:
        _cancel(bet, payload)


def _spawn(bet: Bet, payload: dict[str, Any]) -> None:
    node_id = payload["node_id"]
    parent_node_id = payload.get("parent_node_id")
    parent = BetNode.objects.filter(bet=bet, node_id=parent_node_id).first() if parent_node_id else None
    defaults = {
        "team_id": bet.team_id,
        "parent": parent,
        "runner": payload.get("runner") or "",
        "depth": payload.get("depth") or 0,
        "max_cost": payload.get("max_cost"),
        "max_depth": payload.get("max_depth"),
        "max_children": payload.get("max_children"),
        "sandbox_external_id": payload.get("sandbox_external_id"),
    }
    node, created = BetNode.objects.get_or_create(bet=bet, node_id=node_id, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            setattr(node, field, value)
        node.status = NodeStatus.SPAWNED
        node.save(update_fields=[*defaults.keys(), "status", "updated_at"])


def _finish(bet: Bet, payload: dict[str, Any], status: NodeStatus) -> None:
    node_id = payload["node_id"]
    node, _ = BetNode.objects.get_or_create(bet=bet, node_id=node_id, defaults={"team_id": bet.team_id})
    node.status = status
    cost = payload.get("cost")
    if cost is not None:
        node.cost_so_far = cost
    node.save(update_fields=["status", "cost_so_far", "updated_at"])


def _cancel(bet: Bet, payload: dict[str, Any]) -> None:
    node_id = payload.get("node_id")
    if not node_id:
        return
    BetNode.objects.filter(bet=bet, node_id=node_id).update(status=NodeStatus.CANCELLED)
