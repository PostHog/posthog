from datetime import timedelta

import pytest

from django.utils import timezone

from products.wizard.backend.facade.enums import (
    WizardRunDispatchStatus,
    WizardRunEnvironment,
    WizardRunStatus,
    WizardWorkspaceType,
)
from products.wizard.backend.facade.errors import (
    ActiveWizardRunError,
    WizardRunDailyLimitError,
    WizardRunHourlyLimitError,
)
from products.wizard.backend.logic.programs import program_to_mapping
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM
from products.wizard.backend.logic.runs.admission import enforce_cloud_run_creation_policy
from products.wizard.backend.models import WizardRun


def _create_cloud_run(team_id: int, user_id: int, status: WizardRunStatus, age: timedelta) -> WizardRun:
    run = WizardRun.objects.for_team(team_id).create(
        team_id=team_id,
        created_by_id=user_id,
        environment=WizardRunEnvironment.CLOUD.value,
        workspace_type=WizardWorkspaceType.GIT_REPOSITORY.value,
        workspace={"repository": "posthog/posthog"},
        program=program_to_mapping(POSTHOG_INTEGRATION_PROGRAM),
        status=status.value,
        dispatch_status=WizardRunDispatchStatus.DISPATCHED.value,
    )
    WizardRun.objects.for_team(team_id).filter(id=run.id).update(created_at=timezone.now() - age)
    return run


@pytest.mark.django_db
def test_cloud_admission_rejects_an_active_run(team, user) -> None:
    _create_cloud_run(team.id, user.id, WizardRunStatus.RUNNING, timedelta(minutes=5))

    with pytest.raises(ActiveWizardRunError):
        enforce_cloud_run_creation_policy(team.id, user.id)


@pytest.mark.django_db
def test_cloud_admission_limits_hourly_runs(team, user) -> None:
    _create_cloud_run(team.id, user.id, WizardRunStatus.COMPLETED, timedelta(minutes=10))
    _create_cloud_run(team.id, user.id, WizardRunStatus.FAILED, timedelta(minutes=20))

    with pytest.raises(WizardRunHourlyLimitError):
        enforce_cloud_run_creation_policy(team.id, user.id)


@pytest.mark.django_db
def test_cloud_admission_limits_daily_runs(team, user) -> None:
    for hours in (2, 3, 4, 5, 6):
        _create_cloud_run(team.id, user.id, WizardRunStatus.COMPLETED, timedelta(hours=hours))

    with pytest.raises(WizardRunDailyLimitError):
        enforce_cloud_run_creation_policy(team.id, user.id)


@pytest.mark.django_db
def test_cloud_admission_ignores_historical_runs(team, user) -> None:
    _create_cloud_run(team.id, user.id, WizardRunStatus.COMPLETED, timedelta(days=2))

    enforce_cloud_run_creation_policy(team.id, user.id)
