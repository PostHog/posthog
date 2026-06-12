from datetime import datetime, timedelta

from django.utils import timezone

from products.wizard.backend.facade.contracts import STALE_AFTER
from products.wizard.backend.facade.enums import RunPhase


def is_stale(run_phase: RunPhase, updated_at: datetime, stale_after: timedelta = STALE_AFTER) -> bool:
    """Determine if a session is stale based on its last update time."""
    if run_phase in {RunPhase.COMPLETED, RunPhase.ERROR}:
        return False

    return timezone.now() - updated_at > stale_after
