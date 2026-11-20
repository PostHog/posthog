"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from posthog.temporal.common.registration import ActivityDefinition, QueueBinding, TemporalRegistration

from ..temporal.activities import finalize_highlights_activity, resolve_pins_activity, run_highlight_source_activity
from ..temporal.schedule import delete_today_briefing_schedule as delete_today_briefing_schedule
from ..temporal.workflows import ComputeTodayHighlightsWorkflow

WORKFLOWS = [ComputeTodayHighlightsWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    run_highlight_source_activity,
    resolve_pins_activity,
    finalize_highlights_activity,
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    schedules=(delete_today_briefing_schedule,),
)
