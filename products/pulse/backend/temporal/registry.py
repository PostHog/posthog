from typing import TYPE_CHECKING

from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [GenerateProductBriefWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    gather_brief_inputs_activity,
    synthesize_brief_activity,
    mark_brief_failed_activity,
]
