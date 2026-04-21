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
    """Delete orphaned rows from posthog_featureflaghashkeyoverride.

    The table has no FK to FeatureFlag (feature_flag_key is a CharField), so rows
    orphan on two paths:

    1. Soft-delete without rename — row stays with deleted=True, original key intact.
    2. In-place rename — FeatureFlagSerializer.update() (posthog/api/feature_flag.py:1587-1588)
       updates FeatureFlag.key without cascading to FeatureFlagHashKeyOverride.feature_flag_key.
       Note: soft-delete + key reuse is ruled out by UniqueConstraint(team, key) on
       FeatureFlag (posthog/models/feature_flag/feature_flag.py:126).

    Safety note: flag_matching (posthog/models/feature_flag/flag_matching.py:700-701)
    looks up overrides by the live FeatureFlag.key, so rows whose key has drifted are
    already unreachable at evaluation time — deleting them is pure storage reclamation,
    not a behavior change. Experience continuity silently re-writes under the new key
    on the next eval (flag_matching.py:1151).

    The two tables also live in different databases (persons_db vs default per
    posthog/person_db_router.py), so we iterate per team rather than run a single
    cross-database query.
    """
    # Source teams from the overrides table so cleanup covers teams whose flags were all
    # hard-deleted (no surviving FeatureFlag row).
    team_ids = list(FeatureFlagHashKeyOverride.objects.values_list("team_id", flat=True).distinct())

    total_deleted = 0
    total_stale_keys = 0
    teams_processed = 0
    teams_failed = 0
    failed_team_ids: list[int] = []

    for team_id in team_ids:
        try:
            # TOCTOU note: between these two selects, an in-place rename + an eval-triggered
            # override write for the new key can put the fresh key in override_keys but not
            # live_keys, so the fresh row gets deleted. Weekly cadence + per-team scan keeps
            # the window small; blast radius is one eval cycle (the override re-writes on
            # the next evaluation). Documented rather than fixed.
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
            stale_qs = FeatureFlagHashKeyOverride.objects.filter(team_id=team_id, feature_flag_key__in=stale_keys)

            if config.dry_run:
                total_deleted += stale_qs.count()
            else:
                # Row-level batching: a single stale key can have unbounded override rows
                # (one per person), so bound each DELETE by config.batch_size rows to keep
                # individual transactions and WAL predictable.
                while True:
                    ids = list(stale_qs.values_list("id", flat=True)[: config.batch_size])
                    if not ids:
                        break
                    count, _ = FeatureFlagHashKeyOverride.objects.filter(id__in=ids).delete()
                    total_deleted += count
                    if len(ids) < config.batch_size:
                        break

            teams_processed += 1
        except Exception:
            teams_failed += 1
            failed_team_ids.append(team_id)
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

    metadata: dict[str, dagster.MetadataValue] = {
        "teams_processed": dagster.MetadataValue.int(teams_processed),
        "teams_failed": dagster.MetadataValue.int(teams_failed),
        "failed_team_ids": dagster.MetadataValue.json(failed_team_ids),
        "stale_keys_found": dagster.MetadataValue.int(total_stale_keys),
        "rows_deleted": dagster.MetadataValue.int(total_deleted),
        "dry_run": dagster.MetadataValue.bool(config.dry_run),
    }

    # Surface metadata on the Failure so the Dagster UI (and regression tests) can
    # inspect teams_failed / failed_team_ids even when the run fails. Success path
    # still returns MaterializeResult as before. Mirrors the pattern in
    # products/data_warehouse/dags/managed_viewset_sync.py:80-81.
    if teams_failed > 0:
        raise dagster.Failure(
            description=f"hash_key_override_cleanup failed for {teams_failed}/{len(team_ids)} teams",
            metadata=metadata,
        )

    return dagster.MaterializeResult(metadata=metadata)


hash_key_override_cleanup_job = dagster.define_asset_job(
    name="hash_key_override_cleanup_job",
    selection=[hash_key_override_cleanup.key],
    tags={"owner": JobOwners.TEAM_FLAGS_PLATFORM.value},
)


@dagster.schedule(
    job=hash_key_override_cleanup_job,
    cron_schedule="0 4 * * 0",  # Weekly on Sunday at 4 AM UTC
    execution_timezone="UTC",
    # STOPPED by default: the table may be large and the DELETE code path is never
    # exercised in dry-run (dry-run only counts). First rollout should be a manual
    # canary: operator triggers dry-run → single-team real delete via config override
    # → watches Postgres metrics → then flips the schedule on.
    default_status=dagster.DefaultScheduleStatus.STOPPED,
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
