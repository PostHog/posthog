import dagster
import structlog

from posthog.dags.common import JobOwners
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride

logger = structlog.get_logger(__name__)


class HashKeyOverrideCleanupConfig(dagster.Config):
    batch_size: int = 1000
    dry_run: bool = False


@dagster.asset(tags={"owner": JobOwners.TEAM_FLAGS_PLATFORM.value})
def hash_key_override_cleanup(
    context: dagster.AssetExecutionContext,
    config: HashKeyOverrideCleanupConfig,
) -> dagster.MaterializeResult:
    # FeatureFlagHashKeyOverride has no FK to FeatureFlag (stores `feature_flag_key` as a string),
    # so rows orphan on any deletion path: soft-delete, soft-delete-with-rename, and the flag
    # create path's hard-delete of soft-deleted rows with reused keys. The two tables also live
    # in different databases (persons_db vs default), so we iterate per team rather than run
    # a single cross-database query.
    team_ids = list(FeatureFlag.objects_including_soft_deleted.values_list("team_id", flat=True).distinct())

    total_deleted = 0
    total_stale_keys = 0
    teams_processed = 0
    teams_failed = 0

    for team_id in team_ids:
        try:
            live_keys = set(FeatureFlag.objects.filter(team_id=team_id, deleted=False).values_list("key", flat=True))
            override_keys = set(
                FeatureFlagHashKeyOverride.objects.filter(team_id=team_id)
                .values_list("feature_flag_key", flat=True)
                .distinct()
            )
            stale_keys = list(override_keys - live_keys)
            if not stale_keys:
                teams_processed += 1
                continue

            total_stale_keys += len(stale_keys)

            for i in range(0, len(stale_keys), config.batch_size):
                batch = stale_keys[i : i + config.batch_size]
                qs = FeatureFlagHashKeyOverride.objects.filter(team_id=team_id, feature_flag_key__in=batch)
                if config.dry_run:
                    total_deleted += qs.count()
                else:
                    count, _ = qs.delete()
                    total_deleted += count

            teams_processed += 1
        except Exception:
            teams_failed += 1
            logger.exception("hash_key_override_cleanup_team_failed", team_id=team_id)

    context.log.info(
        "hash_key_override_cleanup_complete",
        extra={
            "teams_processed": teams_processed,
            "teams_failed": teams_failed,
            "stale_keys_found": total_stale_keys,
            "rows_deleted": total_deleted,
            "dry_run": config.dry_run,
        },
    )

    return dagster.MaterializeResult(
        metadata={
            "teams_processed": dagster.MetadataValue.int(teams_processed),
            "teams_failed": dagster.MetadataValue.int(teams_failed),
            "stale_keys_found": dagster.MetadataValue.int(total_stale_keys),
            "rows_deleted": dagster.MetadataValue.int(total_deleted),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


hash_key_override_cleanup_job = dagster.define_asset_job(
    name="hash_key_override_cleanup_job",
    selection=[hash_key_override_cleanup.key],
    tags={"owner": JobOwners.TEAM_FLAGS_PLATFORM.value},
)


@dagster.schedule(
    job=hash_key_override_cleanup_job,
    cron_schedule="0 4 * * 0",  # Weekly on Sunday at 4 AM UTC
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def weekly_hash_key_override_cleanup_schedule(context):
    return dagster.RunRequest(
        run_key=f"hash_key_override_cleanup_{context.scheduled_execution_time.strftime('%Y%m%d')}",
        run_config={
            "ops": {
                "hash_key_override_cleanup": {"config": HashKeyOverrideCleanupConfig().model_dump()},
            }
        },
    )
