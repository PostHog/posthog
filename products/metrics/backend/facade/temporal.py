"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule.

`SOURCE_EVALUATION_*` is the metrics source's evaluation on the shared alerts platform, which core
registers on the platform's evaluation queue rather than on this product's own queue.
"""

from products.metrics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.metrics.backend.temporal.alert_evaluate import SOURCE_EVALUATION_ACTIVITIES, SOURCE_EVALUATION_WORKFLOWS
from products.metrics.backend.temporal.schedule import (
    create_suggested_dashboards_discovery_schedule as create_suggested_dashboards_discovery_schedule,
)

__all__ = [
    "ACTIVITIES",
    "SOURCE_EVALUATION_ACTIVITIES",
    "SOURCE_EVALUATION_WORKFLOWS",
    "WORKFLOWS",
    "create_suggested_dashboards_discovery_schedule",
]
