from datetime import datetime, timedelta

from django.utils import timezone

from products.wizard.backend.facade.enums import WizardSessionRunPhase
from products.wizard.backend.logic.sessions.config import STALE_AFTER


def is_stale(run_phase: WizardSessionRunPhase, updated_at: datetime, stale_after: timedelta = STALE_AFTER) -> bool:
    """Determine if a session is stale based on its last update time."""
    if run_phase in {WizardSessionRunPhase.COMPLETED, WizardSessionRunPhase.ERROR}:
        return False

    return timezone.now() - updated_at > stale_after
