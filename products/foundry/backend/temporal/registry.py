"""Workflow and activity registration lists for the foundry Temporal worker.

Kept separate from ``temporal/__init__.py`` (owned elsewhere) so the worker wiring has a
stable import target: ``from products.foundry.backend.temporal.registry import WORKFLOWS, ACTIVITIES``.
"""

from __future__ import annotations

from products.foundry.backend.temporal.activities import record_bet_event_activity, run_node_activity
from products.foundry.backend.temporal.workflow import FoundryNodeWorkflow

WORKFLOWS = [FoundryNodeWorkflow]

ACTIVITIES = [run_node_activity, record_bet_event_activity]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
