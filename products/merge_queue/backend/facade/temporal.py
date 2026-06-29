"""Facade re-exports for the Stampede Temporal surface.

The wiring the Temporal worker registers and the engine dispatches on — exposed through the
facade so external callers never reach into `backend/temporal/` internals.
"""

from products.merge_queue.backend.temporal import ACTIVITIES, WORKFLOWS
from products.merge_queue.backend.temporal.client import start_trial_workflow

__all__ = ["ACTIVITIES", "WORKFLOWS", "start_trial_workflow"]
