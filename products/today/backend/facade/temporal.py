"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from collections.abc import Callable
from typing import Any

from ..temporal.activities import (
    collect_and_draft_activity,
    mark_failed_activity,
    start_due_briefings_activity,
    write_and_check_activity,
)
from ..temporal.schedule import create_today_briefing_schedule as create_today_briefing_schedule
from ..temporal.workflows import GenerateTodayBriefingWorkflow, TodayBriefingSchedulerWorkflow

WORKFLOWS = [GenerateTodayBriefingWorkflow, TodayBriefingSchedulerWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    collect_and_draft_activity,
    write_and_check_activity,
    mark_failed_activity,
    start_due_briefings_activity,
]
