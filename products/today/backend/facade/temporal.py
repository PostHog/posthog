"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from collections.abc import Callable
from typing import Any

from ..temporal.activities import (
    collect_news_facts_activity,
    fail_news_activity,
    finalize_highlights_activity,
    resolve_pins_activity,
    run_highlight_source_activity,
    write_news_activity,
)
from ..temporal.schedule import delete_today_briefing_schedule as delete_today_briefing_schedule
from ..temporal.workflows import ComputeTodayHighlightsWorkflow, GenerateTodayNewsWorkflow

WORKFLOWS = [ComputeTodayHighlightsWorkflow, GenerateTodayNewsWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    run_highlight_source_activity,
    resolve_pins_activity,
    finalize_highlights_activity,
    collect_news_facts_activity,
    write_news_activity,
    fail_news_activity,
]
