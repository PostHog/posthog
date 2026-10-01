"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from collections.abc import Callable
from typing import Any

from ..temporal.activities import mark_failed_activity, run_agent_activity, start_due_briefings_activity
from ..temporal.schedule import create_today_briefing_schedule as create_today_briefing_schedule
from ..temporal.workflows import GenerateTodayBriefingWorkflow, TodayBriefingSchedulerWorkflow

WORKFLOWS = [GenerateTodayBriefingWorkflow, TodayBriefingSchedulerWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [run_agent_activity, mark_failed_activity, start_due_briefings_activity]
