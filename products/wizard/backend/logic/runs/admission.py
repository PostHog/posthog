from django.utils import timezone

from posthog.models import Team

from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import (
    ActiveWizardRunError,
    WizardRunDailyLimitError,
    WizardRunHourlyLimitError,
)
from products.wizard.backend.logic.runs.config import (
    CLOUD_RUN_DAILY_LIMIT,
    CLOUD_RUN_DAILY_WINDOW,
    CLOUD_RUN_HOURLY_LIMIT,
    CLOUD_RUN_HOURLY_WINDOW,
)
from products.wizard.backend.models import WizardRun


def enforce_cloud_run_creation_policy(team_id: int, created_by_id: int, idempotency_key: str | None = None) -> None:
    Team.objects.select_for_update().only("id").get(id=team_id)

    runs = WizardRun.objects.for_team(team_id).filter(
        created_by_id=created_by_id,
        environment=WizardRunEnvironment.CLOUD.value,
    )

    if idempotency_key is not None:
        runs = runs.exclude(idempotency_key=idempotency_key)

    if runs.filter(status__in=(WizardRunStatus.CREATED.value, WizardRunStatus.RUNNING.value)).exists():
        raise ActiveWizardRunError

    now = timezone.now()

    if runs.filter(created_at__gte=now - CLOUD_RUN_HOURLY_WINDOW).count() >= CLOUD_RUN_HOURLY_LIMIT:
        raise WizardRunHourlyLimitError

    if runs.filter(created_at__gte=now - CLOUD_RUN_DAILY_WINDOW).count() >= CLOUD_RUN_DAILY_LIMIT:
        raise WizardRunDailyLimitError
