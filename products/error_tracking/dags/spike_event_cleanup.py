import datetime

from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners

from products.error_tracking.backend.models import ErrorTrackingSpikeEvent

SPIKE_EVENT_RETENTION_DAYS = 30


class SpikeEventCleanupConfig(dagster.Config):
    days_old: int = SPIKE_EVENT_RETENTION_DAYS


@dagster.asset(tags={"owner": JobOwners.TEAM_ERROR_TRACKING.value})
def spike_events_cleanup(
    context: dagster.AssetExecutionContext,
    config: SpikeEventCleanupConfig,
) -> dagster.MaterializeResult:
    cutoff = timezone.now() - datetime.timedelta(days=config.days_old)
    qs = ErrorTrackingSpikeEvent.objects.filter(detected_at__lt=cutoff)

    deleted, _ = qs.delete()
    context.log.info("Deleted %d spike events older than %s", deleted, cutoff.isoformat())

    return dagster.MaterializeResult(metadata={"deleted_count": dagster.MetadataValue.int(deleted)})


spike_event_cleanup_job = dagster.define_asset_job(
    name="spike_event_cleanup_job",
    selection=[spike_events_cleanup.key],
    tags={"owner": JobOwners.TEAM_ERROR_TRACKING.value},
)


@dagster.schedule(
    job=spike_event_cleanup_job,
    cron_schedule="0 4 * * *",  # Daily at 4 AM UTC
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def daily_spike_event_cleanup_schedule(context):
    return dagster.RunRequest(
        run_key=f"spike_event_cleanup_{context.scheduled_execution_time.strftime('%Y%m%d')}",
        run_config={
            "ops": {
                "spike_events_cleanup": {"config": SpikeEventCleanupConfig().model_dump()},
            }
        },
    )
