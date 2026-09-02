"""Postgres fixtures that stage every Integration health / diagnose state.

Source health is computed purely from ExternalDataSource / ExternalDataSchema /
ExternalDataJob rows, so each platform below is staged into a different
`last_sync_status`, plus one platform deliberately left without a source at all.
"""

import datetime as dt

from django.utils import timezone

from posthog.models import Team

from products.marketing_analytics.backend.services.native_integrations import EXTERNAL_SOURCE_TYPE_TO_NATIVE
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import (
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSourceStatus,
)

# platform -> (schema names, staged state). Only data-preserving states are used
# (ok / stale / error / tables_disabled) so every platform still shows cost data
# in the dashboard while the health surfaces stay non-trivial.
PLATFORM_STATES: dict[str, tuple[tuple[str, ...], str]] = {
    "GoogleAds": (("campaign", "campaign_overview_stats", "ad_group", "ad_group_stats", "ad", "ad_stats"), "ok"),
    "MetaAds": (("campaigns", "campaign_stats"), "ok"),
    "LinkedinAds": (("campaign_groups", "campaign_group_stats"), "ok"),
    "RedditAds": (("campaigns", "campaign_report"), "ok"),
    "BingAds": (("campaigns", "campaign_performance_report"), "stale"),
    "SnapchatAds": (("campaigns", "campaign_stats_daily"), "error"),
    "TikTokAds": (("campaigns", "campaign_report"), "tables_disabled"),
}

# Left without a source so the diagnose service reports `events_only`, which is the
# only way the setup plan reaches `connect_source`. Reddit keeps its paid campaign, so
# the suggestion is correct there and fires. Reddit was in the `ok` state, so no health
# scenario is lost — its cost-table format is, and `--connect-all` brings it back.
UNCONNECTED_PLATFORMS: frozenset[str] = frozenset({"RedditAds"})

# Absent from PLATFORM_STATES entirely rather than listed above, because `--connect-all`
# must not connect them: they send organic traffic only, which is the half the paid gate
# suppresses, so they reach `events_only` and draw no suggestion. That's the mirror of
# Reddit and the pair is the point of the fixture. Named here so the dry-run summary can
# count them — deriving `events_only` from PLATFORM_STATES alone silently misses them.
ORGANIC_ONLY_PLATFORMS: frozenset[str] = frozenset({"PinterestAds"})


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


def create_sources(team: Team, *, unconnected: frozenset[str] = UNCONNECTED_PLATFORMS) -> dict[str, ExternalDataSource]:
    """Create one ExternalDataSource per staged platform (replacing previous demo runs).

    Platforms in `unconnected` are skipped and get no row, which is what puts them in
    `events_only`. Callers must treat a missing key as "no source", not an error.
    """
    # Retire every previous demo fixture across all native platforms first — including
    # ones since dropped from PLATFORM_STATES (e.g. a platform moved to organic-only
    # traffic). Retiring inside the create loop would miss those, leaving a stale source
    # live so the diagnostic keeps the platform "connected" and re-seeding never reaches
    # events_only. Scoped to the marketing-demo- prefix so real integrations are untouched.
    ExternalDataSource.objects.filter(
        team=team,
        source_type__in=EXTERNAL_SOURCE_TYPE_TO_NATIVE.keys(),
        deleted=False,
        source_id__startswith="marketing-demo-",
    ).update(deleted=True)

    sources: dict[str, ExternalDataSource] = {}
    for platform in PLATFORM_STATES:
        if platform in unconnected:
            continue
        sources[platform] = ExternalDataSource.objects.create(
            team=team,
            source_id=f"marketing-demo-{platform.lower()}",
            connection_id=f"marketing-demo-{platform.lower()}",
            status=ExternalDataSourceStatus.COMPLETED,
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
        source = sources.get(platform)
        if source is None:  # deliberately unconnected
            continue
        for schema_name in schema_names:
            schema_status: str | None = ExternalDataSchemaStatus.COMPLETED
            should_sync = True
            if state == "tables_failed" and schema_name == schema_names[-1]:
                schema_status = ExternalDataSchemaStatus.FAILED
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
            _create_job(source, status=ExternalDataJobStatus.COMPLETED, age=dt.timedelta(hours=1), rows_synced=5000)
        elif state == "stale":
            _create_job(source, status=ExternalDataJobStatus.COMPLETED, age=dt.timedelta(hours=30), rows_synced=4200)
        elif state == "error":
            _create_job(source, status=ExternalDataJobStatus.COMPLETED, age=dt.timedelta(days=3), rows_synced=3100)
            _create_job(
                source,
                status=ExternalDataJobStatus.FAILED,
                age=dt.timedelta(hours=1),
                latest_error="Authentication failed: refresh token expired",
            )
        elif state in ("tables_missing", "tables_failed", "tables_disabled"):
            _create_job(source, status=ExternalDataJobStatus.COMPLETED, age=dt.timedelta(hours=2), rows_synced=900)
        # "never": no jobs at all
