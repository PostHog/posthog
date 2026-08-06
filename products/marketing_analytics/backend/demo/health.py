"""Postgres fixtures that stage every Integration health / diagnose state.

Source health is computed purely from ExternalDataSource / ExternalDataSchema /
ExternalDataJob rows, so each platform below is staged into a different
`last_sync_status`. TikTok is deliberately not created: its traffic makes the
diagnose service report `events_only`.
"""

import datetime as dt

from django.utils import timezone

from posthog.models import Team

from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)

# platform -> (schema names, staged state). Only data-preserving states are used
# (ok / stale / error / tables_disabled) so every platform still shows cost data
# in the dashboard while the health surfaces stay non-trivial.
PLATFORM_STATES: dict[str, tuple[tuple[str, ...], str]] = {
    "GoogleAds": (("campaign", "campaign_overview_stats", "ad_group", "ad_group_stats", "ad", "ad_stats"), "ok"),
    "MetaAds": (("campaigns", "campaign_stats"), "ok"),
    "LinkedinAds": (("campaign_groups", "campaign_group_stats"), "ok"),
    "RedditAds": (("campaigns", "campaign_report"), "ok"),
    "PinterestAds": (("campaigns", "campaign_analytics"), "ok"),
    "BingAds": (("campaigns", "campaign_performance_report"), "stale"),
    "SnapchatAds": (("campaigns", "campaign_stats_daily"), "error"),
    "TikTokAds": (("campaigns", "campaign_report"), "tables_disabled"),
}


def _create_job(
    source: ExternalDataSource,
    *,
    status: str,
    age: dt.timedelta,
    rows_synced: int | None = None,
    latest_error: str | None = None,
) -> None:
    now = timezone.now()
    job = ExternalDataJob.objects.create(
        team=source.team,
        pipeline=source,
        status=status,
        rows_synced=rows_synced,
        latest_error=latest_error,
        finished_at=now - age,
    )
    ExternalDataJob.objects.filter(id=job.id).update(created_at=now - age)


def create_sources(team: Team) -> dict[str, ExternalDataSource]:
    """Create one ExternalDataSource per staged platform (replacing previous demo runs)."""
    sources: dict[str, ExternalDataSource] = {}
    for platform in PLATFORM_STATES:
        # Only retire previous demo fixtures - never a real integration the team may have.
        ExternalDataSource.objects.filter(
            team=team, source_type=platform, deleted=False, source_id__startswith="marketing-demo-"
        ).update(deleted=True)
        sources[platform] = ExternalDataSource.objects.create(
            team=team,
            source_id=f"marketing-demo-{platform.lower()}",
            connection_id=f"marketing-demo-{platform.lower()}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=platform,
            prefix="",
        )
    return sources


def stage_schemas_and_jobs(
    team: Team,
    sources: dict[str, ExternalDataSource],
    table_by_platform_schema: dict[tuple[str, str], DataWarehouseTable | None],
) -> None:
    now = timezone.now()
    for platform, (schema_names, state) in PLATFORM_STATES.items():
        source = sources[platform]
        for schema_name in schema_names:
            schema_status: str | None = ExternalDataSchema.Status.COMPLETED
            should_sync = True
            if state == "tables_failed" and schema_name == schema_names[-1]:
                schema_status = ExternalDataSchema.Status.FAILED
            if state == "tables_disabled" and schema_name == schema_names[-1]:
                should_sync = False
            if state == "never":
                schema_status = None
            ExternalDataSchema.objects.create(
                team=team,
                source=source,
                name=schema_name,
                table=table_by_platform_schema.get((platform, schema_name)),
                should_sync=should_sync,
                status=schema_status,
                last_synced_at=None if state == "never" else now - dt.timedelta(hours=1),
            )
        if state == "ok":
            _create_job(source, status=ExternalDataJob.Status.COMPLETED, age=dt.timedelta(hours=1), rows_synced=5000)
        elif state == "stale":
            _create_job(source, status=ExternalDataJob.Status.COMPLETED, age=dt.timedelta(hours=30), rows_synced=4200)
        elif state == "error":
            _create_job(source, status=ExternalDataJob.Status.COMPLETED, age=dt.timedelta(days=3), rows_synced=3100)
            _create_job(
                source,
                status=ExternalDataJob.Status.FAILED,
                age=dt.timedelta(hours=1),
                latest_error="Authentication failed: refresh token expired",
            )
        elif state in ("tables_missing", "tables_failed", "tables_disabled"):
            _create_job(source, status=ExternalDataJob.Status.COMPLETED, age=dt.timedelta(hours=2), rows_synced=900)
        # "never": no jobs at all
