from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_with_activity_context


@dataclass(frozen=True)
class UpdateBabysitRunStateInput:
    run_id: str
    updates: dict[str, Any] = field(default_factory=dict)


@activity.defn
@asyncify
def update_babysit_run_state(input: UpdateBabysitRunStateInput) -> None:
    """Persist a babysit-loop transition onto the run row for the desktop's status UI."""
    log_with_activity_context(
        "update_babysit_run_state",
        run_id=input.run_id,
        keys=sorted(input.updates.keys()),
    )
    TaskRun.update_state_atomic(input.run_id, updates=input.updates)
