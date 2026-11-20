from typing import TYPE_CHECKING

from products.today.backend.temporal.activities import (
    finalize_highlights_activity,
    resolve_pins_activity,
    run_highlight_source_activity,
)
from products.today.backend.temporal.workflows import ComputeTodayHighlightsWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [ComputeTodayHighlightsWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    run_highlight_source_activity,
    resolve_pins_activity,
    finalize_highlights_activity,
]
