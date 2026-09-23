from temporalio import activity

from posthog.models import Team
from posthog.models.team.logs_retention import (
    DEFAULT_LOGS_RETENTION_DAYS,
    required_logs_retention_feature,
    reset_logs_retention_rules,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.logs.backend.models import LogsRetentionRule
from products.logs.backend.temporal.retention_entitlements.types import (
    EnforceLogsRetentionEntitlementsInput,
    EnforceLogsRetentionEntitlementsOutput,
)

LOGGER = get_write_only_logger(__name__)


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
            Team.objects.filter(logs_settings__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS)
            .select_related("organization")
            .only("id", "name", "organization", "organization__available_product_features", "logs_settings")
        ):
            logs_settings = team.logs_settings or {}
            retention_days = logs_settings.get("retention_days")
            if not isinstance(retention_days, int):
                continue

            required_feature = required_logs_retention_feature(retention_days)
            if not required_feature:
                continue

            teams_checked += 1
            organization = team.organization
            if organization.is_feature_available(required_feature):
                continue

            # Preserve unrelated Logs settings such as JSON parsing and PII scrubbing.
            team.logs_settings = {
                **logs_settings,
                "retention_days": DEFAULT_LOGS_RETENTION_DAYS,
            }
            teams_to_update.append(team)

            logger.info(
                "Logs retention period setting forcibly reduced",
                team_id=team.id,
                team_name=team.name,
                organization_id=organization.id,
                retention_period_before=retention_days,
                retention_period_after=DEFAULT_LOGS_RETENTION_DAYS,
            )

            if teams_checked % batch_size == 0:
                logger.info("Processed Logs retention entitlement batch", teams_checked=teams_checked)

        if not input.dry_run and teams_to_update:
            await database_sync_to_async(Team.objects.bulk_update)(
                teams_to_update,
                ["logs_settings"],
                batch_size=batch_size,
            )

        # Rules store their own retention period, so ingestion keeps applying a paid period until they are reset too.
        rules_to_update: list[LogsRetentionRule] = []
        rules_checked = 0
        async for rule in (
            LogsRetentionRule.objects.filter(config__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS)
            .select_related("team__organization")
            .only("id", "config", "version", "team__id", "team__organization__available_product_features")
        ):
            retention_days = rule.config.get("retention_days")
            if not isinstance(retention_days, int):
                continue
            required_feature = required_logs_retention_feature(retention_days)
            if not required_feature:
                continue

            rules_checked += 1
            organization = rule.team.organization
            if organization.is_feature_available(required_feature):
                continue
            rules_to_update.append(rule)
            logger.info(
                "Logs retention rule period forcibly reduced",
                rule_id=str(rule.id),
                team_id=rule.team_id,
                organization_id=organization.id,
                retention_period_before=retention_days,
                retention_period_after=DEFAULT_LOGS_RETENTION_DAYS,
            )

        if not input.dry_run and rules_to_update:
            await database_sync_to_async(reset_logs_retention_rules)(rules_to_update)

        logger.info(
            "Logs retention entitlement enforcement complete",
            teams_checked=teams_checked,
            teams_reset=len(teams_to_update),
            rules_checked=rules_checked,
            rules_reset=len(rules_to_update),
        )
        return EnforceLogsRetentionEntitlementsOutput(
            teams_checked=teams_checked,
            teams_reset=len(teams_to_update),
            rules_checked=rules_checked,
            rules_reset=len(rules_to_update),
        )
