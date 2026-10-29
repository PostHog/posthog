"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule.

Kept apart from ``facade/api.py`` so ``temporalio`` stays off the light data-surface import path.
"""

from products.subscriptions.backend.temporal import ACTIVITIES, WORKFLOWS
from products.subscriptions.backend.temporal.schedule import create_schedule_all_subscriptions_schedule

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "create_schedule_all_subscriptions_schedule",
]
