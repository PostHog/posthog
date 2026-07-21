import uuid

import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team

from products.logs.backend.temporal.retention_entitlements.activities import enforce_logs_retention_entitlements
from products.logs.backend.temporal.retention_entitlements.types import (
    EnforceLogsRetentionEntitlementsInput,
    EnforceLogsRetentionEntitlementsOutput,
)


async def _create_organization(features: list[AvailableFeature]) -> Organization:
    organization = await sync_to_async(Organization.objects.create)(name=f"Test org {uuid.uuid4()}")
    organization.available_product_features = [{"key": feature, "name": feature.value} for feature in features]
    await sync_to_async(organization.save)()
    return organization


async def _create_team(organization: Organization, retention_days: int, **logs_settings: object) -> Team:
    return await sync_to_async(Team.objects.create)(
        organization=organization,
        name=f"Test team {uuid.uuid4()}",
        api_token=str(uuid.uuid4()),
        logs_settings={
            "retention_days": retention_days,
            **logs_settings,
        },
    )


async def _refresh_team(team: Team) -> Team:
    return await sync_to_async(Team.objects.get)(id=team.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_enforce_logs_retention_entitlements_resets_only_over_entitled_teams() -> None:
    org_with_30d = await _create_organization([AvailableFeature.LOGS_RETENTION_30D])
    org_with_90d = await _create_organization([AvailableFeature.LOGS_RETENTION_90D])
    org_without_retention = await _create_organization([])

    team_14d = await _create_team(org_without_retention, 14)
    team_30d_allowed = await _create_team(org_with_30d, 30)
    team_90d_allowed = await _create_team(org_with_90d, 90)
    team_30d_blocked = await _create_team(
        org_without_retention,
        30,
        capture_console_logs=True,
        retention_last_updated="2026-06-01T00:00:00Z",
    )
    team_90d_blocked = await _create_team(org_without_retention, 90, json_parse_logs=True)

    output: EnforceLogsRetentionEntitlementsOutput = await ActivityEnvironment().run(
        enforce_logs_retention_entitlements,
        EnforceLogsRetentionEntitlementsInput(dry_run=False),
    )

    assert output.teams_checked == 4
    assert output.teams_reset == 2

    assert (await _refresh_team(team_14d)).logs_settings["retention_days"] == 14
    assert (await _refresh_team(team_30d_allowed)).logs_settings["retention_days"] == 30
    assert (await _refresh_team(team_90d_allowed)).logs_settings["retention_days"] == 90

    blocked_30d_settings = (await _refresh_team(team_30d_blocked)).logs_settings
    assert blocked_30d_settings["retention_days"] == 14
    assert blocked_30d_settings["capture_console_logs"] is True
    assert blocked_30d_settings["retention_last_updated"] == "2026-06-01T00:00:00Z"

    blocked_90d_settings = (await _refresh_team(team_90d_blocked)).logs_settings
    assert blocked_90d_settings["retention_days"] == 14
    assert blocked_90d_settings["json_parse_logs"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_enforce_logs_retention_entitlements_dry_run_does_not_update_team() -> None:
    organization = await _create_organization([])
    team = await _create_team(organization, 30)

    output: EnforceLogsRetentionEntitlementsOutput = await ActivityEnvironment().run(
        enforce_logs_retention_entitlements,
        EnforceLogsRetentionEntitlementsInput(dry_run=True),
    )

    assert output.teams_checked == 1
    assert output.teams_reset == 1
    assert (await _refresh_team(team)).logs_settings["retention_days"] == 30
