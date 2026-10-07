import uuid

import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.models import LogsRetentionRule
from products.logs.backend.temporal.retention_entitlements.activities import enforce_logs_retention_entitlements
from products.logs.backend.temporal.retention_entitlements.types import (
    EnforceLogsRetentionEntitlementsInput,
    EnforceLogsRetentionEntitlementsOutput,
)
from products.tracing.backend.facade.retention import TracesRetentionRule
from products.tracing.backend.facade.team_extension import TeamTracingConfig


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


def _rule_fields(retention_days: int) -> dict[str, object]:
    return {
        "name": f"Rule {uuid.uuid4()}",
        "enabled": True,
        "config": {"retention_days": retention_days, "filter_group": {"type": "AND", "values": []}},
    }


async def _create_rule(team: Team, retention_days: int) -> LogsRetentionRule:
    return await sync_to_async(LogsRetentionRule.objects.create)(team=team, **_rule_fields(retention_days))


async def _refresh_rule(rule: LogsRetentionRule) -> LogsRetentionRule:
    return await sync_to_async(LogsRetentionRule.objects.get)(id=rule.id)


async def _create_span_rule(team: Team, retention_days: int) -> TracesRetentionRule:
    return await sync_to_async(TracesRetentionRule.objects.for_team(team.id).create)(
        team=team, **_rule_fields(retention_days)
    )


async def _span_rule_retention(rule: TracesRetentionRule) -> int:
    return (await sync_to_async(TracesRetentionRule.objects.for_team(rule.team_id).get)(id=rule.id)).config[
        "retention_days"
    ]


async def _set_traces_retention(team: Team, retention_days: int) -> None:
    def set_retention() -> None:
        config = get_or_create_team_extension(team, TeamTracingConfig)
        config.retention_days = retention_days
        config.save()

    await sync_to_async(set_retention)()


async def _traces_retention(team: Team) -> int:
    return (await sync_to_async(TeamTracingConfig.objects.get)(team=team)).retention_days


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_enforce_logs_retention_entitlements_resets_only_over_entitled_teams() -> None:
    org_with_30d = await _create_organization([AvailableFeature.LOGS_RETENTION_30D])
    org_without_retention = await _create_organization([])

    team_14d = await _create_team(org_without_retention, 14)
    team_30d_allowed = await _create_team(org_with_30d, 30)
    team_30d_blocked = await _create_team(
        org_without_retention,
        30,
        capture_console_logs=True,
        retention_last_updated="2026-06-01T00:00:00Z",
    )
    team_90d_blocked = await _create_team(org_without_retention, 90)
    # A rule keeps its own period, so a 14-day team can still apply a paid period through it.
    rule_allowed = await _create_rule(team_30d_allowed, 90)
    rule_blocked = await _create_rule(team_14d, 30)
    rule_14d = await _create_rule(team_14d, 14)
    # Traces reuse the Logs entitlement, so a blocked org loses its paid span periods too.
    span_rule_blocked = await _create_span_rule(team_14d, 30)
    span_rule_allowed = await _create_span_rule(team_30d_allowed, 90)
    await _set_traces_retention(team_30d_allowed, 30)
    await _set_traces_retention(team_14d, 30)

    output: EnforceLogsRetentionEntitlementsOutput = await ActivityEnvironment().run(
        enforce_logs_retention_entitlements,
        EnforceLogsRetentionEntitlementsInput(dry_run=False),
    )

    assert output.teams_checked == 3
    assert output.teams_reset == 2
    assert output.rules_checked == 2
    assert output.rules_reset == 1
    assert output.tracing_configs_reset == 1
    assert output.span_rules_reset == 1

    assert (await _refresh_rule(rule_allowed)).config["retention_days"] == 90
    assert (await _refresh_rule(rule_14d)).config["retention_days"] == 14
    assert await _span_rule_retention(span_rule_blocked) == 14
    assert await _span_rule_retention(span_rule_allowed) == 90
    assert await _traces_retention(team_30d_allowed) == 30
    assert await _traces_retention(team_14d) == 14
    blocked_rule = await _refresh_rule(rule_blocked)
    assert blocked_rule.config == {"retention_days": 14, "filter_group": {"type": "AND", "values": []}}
    assert blocked_rule.enabled is True
    assert blocked_rule.version == rule_blocked.version + 1

    assert (await _refresh_team(team_14d)).logs_settings["retention_days"] == 14
    assert (await _refresh_team(team_30d_allowed)).logs_settings["retention_days"] == 30
    assert (await _refresh_team(team_90d_blocked)).logs_settings["retention_days"] == 14

    blocked_30d_settings = (await _refresh_team(team_30d_blocked)).logs_settings
    assert blocked_30d_settings["retention_days"] == 14
    assert blocked_30d_settings["capture_console_logs"] is True
    assert blocked_30d_settings["retention_last_updated"] == "2026-06-01T00:00:00Z"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_enforce_logs_retention_entitlements_dry_run_does_not_update_team() -> None:
    organization = await _create_organization([])
    team = await _create_team(organization, 30)
    rule = await _create_rule(team, 90)

    output: EnforceLogsRetentionEntitlementsOutput = await ActivityEnvironment().run(
        enforce_logs_retention_entitlements,
        EnforceLogsRetentionEntitlementsInput(dry_run=True),
    )

    assert output.teams_checked == 1
    assert output.teams_reset == 1
    assert output.rules_reset == 1
    assert (await _refresh_team(team)).logs_settings["retention_days"] == 30
    assert (await _refresh_rule(rule)).config["retention_days"] == 90
