from collections.abc import Callable
from typing import Any

from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

WORKFLOWS = [GenerateProductBriefWorkflow]
# Typed as the Worker(activities=...) parameter expects, so callers pass it without a mypy cast.
ACTIVITIES: list[Callable[..., Any]] = [
    gather_brief_inputs_activity,
    synthesize_brief_activity,
    mark_brief_failed_activity,
]
