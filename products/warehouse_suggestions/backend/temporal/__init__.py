"""Temporal wiring for warehouse_suggestions. Registered on the data-modeling task queue."""

from collections.abc import Callable
from typing import Any

from posthog.temporal.common.base import PostHogWorkflow

from .activities import generate_warehouse_suggestions, get_warehouse_suggestion_team_batches
from .workflows import WarehouseSuggestionsWorkflow

WORKFLOWS: list[type[PostHogWorkflow]] = [WarehouseSuggestionsWorkflow]

ACTIVITIES: list[Callable[..., Any]] = [get_warehouse_suggestion_team_batches, generate_warehouse_suggestions]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
