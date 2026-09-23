from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.db import OperationalError, connection, connections, transaction
from django.utils import timezone

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    WizardRunCreationResult,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import (
    ActiveWizardRunError,
    WizardRunDailyLimitError,
    WizardRunHourlyLimitError,
)
from products.wizard.backend.logic.programs import program_to_mapping
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM
from products.wizard.backend.logic.runs.admission import lock_cloud_run_creation
from products.wizard.backend.logic.runs.config import CLOUD_RUN_DAILY_LIMIT, CLOUD_RUN_HOURLY_LIMIT
from products.wizard.backend.models import WizardRun


def _create_on_separate_connection(params: CreateWizardRunInput) -> WizardRunCreationResult:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '1s'")
        with team_scope(params.team_id):
            return wizard_facade.create_run_with_result(params)
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "limit,age,policy_error",
    [
        pytest.param(1, timedelta(), ActiveWizardRunError, id="active"),
        pytest.param(CLOUD_RUN_HOURLY_LIMIT, timedelta(minutes=10), WizardRunHourlyLimitError, id="hourly"),
        pytest.param(CLOUD_RUN_DAILY_LIMIT, timedelta(hours=2), WizardRunDailyLimitError, id="daily"),
    ],
)
def test_concurrent_cloud_creation_cannot_bypass_limits(
    team: Team, user: User, limit: int, age: timedelta, policy_error: type[Exception]
) -> None:
    for _ in range(limit - 1):
        run = WizardRun.objects.for_team(team.id).create(
            team_id=team.id,
            created_by_id=user.id,
            environment=WizardRunEnvironment.CLOUD.value,
            workspace_type="git_repository",
            workspace={"repository": "example/project"},
            program=program_to_mapping(POSTHOG_INTEGRATION_PROGRAM),
            status=WizardRunStatus.COMPLETED.value,
        )
        WizardRun.objects.for_team(team.id).filter(id=run.id).update(created_at=timezone.now() - age)

    params = CreateWizardRunInput(
        team_id=team.id,
        created_by_id=user.id,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository="example/project"),
        program_id=POSTHOG_INTEGRATION_PROGRAM.id,
        idempotency_key="first-request",
    )
    competing_params = replace(params, idempotency_key="second-request")

    with (
        patch("products.wizard.backend.logic.runs.lifecycle.authorize_git_repository_access"),
        patch("products.wizard.backend.logic.runs.lifecycle._dispatch_cloud_run"),
    ):
        with transaction.atomic():
            first = wizard_facade.create_run_with_result(params)
            with ThreadPoolExecutor(max_workers=1) as executor:
                competing_request = executor.submit(_create_on_separate_connection, competing_params)
                with pytest.raises(OperationalError, match="lock timeout"):
                    competing_request.result(timeout=10)

            if policy_error is not ActiveWizardRunError:
                WizardRun.objects.for_team(team.id).filter(id=first.run.id).update(
                    status=WizardRunStatus.COMPLETED.value
                )

        with pytest.raises(policy_error):
            wizard_facade.create_run_with_result(competing_params)

        replay = wizard_facade.create_run_with_result(params)
        assert not replay.created
        assert replay.run.id == first.run.id
        assert WizardRun.objects.for_team(team.id).count() == limit


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("other_team,other_user", [(False, True), (True, False)])
def test_admission_lock_does_not_block_other_scopes(team: Team, user: User, other_team: bool, other_user: bool) -> None:
    def acquire_other_scope() -> None:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                lock_cloud_run_creation(team.id + int(other_team), user.id + int(other_user))
                Team.objects.select_for_update(nowait=True).get(id=team.id)
        finally:
            connections.close_all()

    with transaction.atomic():
        lock_cloud_run_creation(team.id, user.id)
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(acquire_other_scope).result(timeout=10)
