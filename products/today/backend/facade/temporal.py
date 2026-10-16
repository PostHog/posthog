"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from collections.abc import Callable
from typing import Any

from ..temporal.activities import (
    finalize_highlights_activity,
    mark_failed_activity,
    run_highlight_source_activity,
    start_due_briefings_activity,
    write_briefing_activity,
)
from ..temporal.schedule import create_today_briefing_schedule as create_today_briefing_schedule
from ..temporal.workflows import (
    ComputeTodayHighlightsWorkflow,
    GenerateTodayBriefingWorkflow,
    TodayBriefingSchedulerWorkflow,
)

WORKFLOWS = [GenerateTodayBriefingWorkflow, TodayBriefingSchedulerWorkflow, ComputeTodayHighlightsWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    write_briefing_activity,
    mark_failed_activity,
    start_due_briefings_activity,
    run_highlight_source_activity,
    finalize_highlights_activity,
]
