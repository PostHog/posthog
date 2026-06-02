from temporalio import activity

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.logs.backend.temporal.retention_entitlements.types import (
    EnforceLogsRetentionEntitlementsInput,
    EnforceLogsRetentionEntitlementsOutput,
)

LOGGER = get_write_only_logger(__name__)

LOGS_RETENTION_FEATURES_BY_DAYS = {
    30: AvailableFeature.LOGS_RETENTION_30D,
    90: AvailableFeature.LOGS_RETENTION_90D,
}


@activity.defn(name="enforce-logs-retention-entitlements")
async def enforce_logs_retention_entitlements(
    input: EnforceLogsRetentionEntitlementsInput,
) -> EnforceLogsRetentionEntitlementsOutput:
    """Reset saved paid Logs retention settings when the organization no longer has the matching feature."""
    async with Heartbeater():
        logger = LOGGER.bind(dry_run=input.dry_run)
        batch_size = max(1, input.batch_size)
        teams_to_update: list[Team] = []
        teams_checked = 0

        # This scans all teams with paid Logs retention enabled. Run it as explicit reconciliation
        # after Billing removes those entitlements; new over-entitled writes are blocked by the API.
        async for team in (
            Team.objects.filter(logs_settings__retention_days__in=list(LOGS_RETENTION_FEATURES_BY_DAYS.keys()))
            .select_related("organization")
            .only("id", "name", "organization", "organization__available_product_features", "logs_settings")
        ):
            logs_settings = team.logs_settings or {}
            retention_days = logs_settings.get("retention_days")
            if not isinstance(retention_days, int):
                continue

            required_feature = LOGS_RETENTION_FEATURES_BY_DAYS.get(retention_days)
            if not required_feature:
                continue

            teams_checked += 1
            organization = await database_sync_to_async(lambda team: team.organization)(team)
            if organization.is_feature_available(required_feature):
                continue

            # Preserve unrelated Logs settings such as JSON parsing and PII scrubbing.
            team.logs_settings = {
                **logs_settings,
                "retention_days": 14,
            }
            teams_to_update.append(team)

            logger.info(
                "Logs retention period setting forcibly reduced",
                team_id=team.id,
                team_name=team.name,
                organization_id=organization.id,
                retention_period_before=retention_days,
                retention_period_after=14,
            )

            if teams_checked % batch_size == 0:
                logger.info("Processed Logs retention entitlement batch", teams_checked=teams_checked)

        if not input.dry_run and teams_to_update:
            await database_sync_to_async(Team.objects.bulk_update)(
                teams_to_update,
                ["logs_settings"],
                batch_size=batch_size,
            )

        logger.info(
            "Logs retention entitlement enforcement complete",
            teams_checked=teams_checked,
            teams_reset=len(teams_to_update),
        )
        return EnforceLogsRetentionEntitlementsOutput(
            teams_checked=teams_checked,
            teams_reset=len(teams_to_update),
        )
