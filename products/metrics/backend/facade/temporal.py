"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from products.metrics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.metrics.backend.temporal.schedule import (
    create_suggested_dashboards_discovery_schedule as create_suggested_dashboards_discovery_schedule,
)

__all__ = ["ACTIVITIES", "WORKFLOWS", "create_suggested_dashboards_discovery_schedule"]
