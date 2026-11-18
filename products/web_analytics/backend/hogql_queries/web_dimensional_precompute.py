"""HogQL INSERT templates for the fixed-dimension web precompute tables.

These are the precomputation-framework successors to the v2 pre-aggregation
`WEB_STATS_INSERT_SQL` / `WEB_BOUNCES_INSERT_SQL` (`posthog/models/web_preaggregated/sql.py`).
Where v2 was hand-written ClickHouse SQL run by a staging-table + partition-swap
Dagster ETL, these are HogQL templates fed to `ensure_precomputed`, which manages
job tracking, TTLs and the `ReplacingMergeTree` INSERTs. The scheduled
`web_dimensional_precompute` Dagster job is the only writer. Query runners only
check for READY jobs (`dimensional_job_ids`) and never build a window inline.

The framework auto-prepends `team_id`/`job_id` and appends `expires_at` to the
top-level SELECT, and substitutes `{time_window_min}` / `{time_window_max}` per
daily job. Buckets are hourly UTC on the session start timestamp (matching the
web_overview lazy precompute), so reads convert team-local windows to UTC before
filtering `period_bucket`.

Parity with v2 is intentional, with two deliberate deviations:
  - `region_name` is taken from the event's `$geoip_subdivision_1_name` (like the
    other geoip dimensions) because the HogQL `sessions` table exposes no initial
    geoip fields. v2 sourced it from the session's initial geoip.
  - `viewport_width`/`viewport_height` coalesce a failed cast to 0 rather than
    NULL, so they fit the non-nullable Int64 columns deterministically.
"""

import json
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from django.conf import settings

from posthog.schema import HogQLQueryModifiers, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.web_preaggregated.sql import is_eu_cluster

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import SESSION_FORWARD_PAD_MINUTES

# Distributed read-table names as registered in the HogQL database schema.
WEB_STATS_DIMENSIONAL_READ_TABLE = "web_stats_dimensional_preaggregated"
WEB_BOUNCES_DIMENSIONAL_READ_TABLE = "web_bounces_dimensional_preaggregated"

# Today's window refreshes hourly, the last two days daily, and older days are held for 90 to 97
# days so a settled day is computed once. The scheduled job re-runs over the rolling window and the
# framework only recomputes windows whose jobs have expired. Today's TTL is shorter than the hourly
# schedule so that every run finds today's job expired and rebuilds it. A TTL equal to the schedule
# period lets a run find the job fresh by seconds, skip it, and leave it expired until the next run.
#
# The jitter gives each older day a stable offset, so a backfill's days expire on different runs
# and each run rebuilds only a few of them.
DIMENSIONAL_TTL_SECONDS: dict[str, int] = {
    "0d": 45 * 60,
    "2d": 24 * 60 * 60,
    "default": 90 * 24 * 60 * 60,
}
DIMENSIONAL_DEFAULT_TTL_JITTER_SECONDS = 7 * 24 * 60 * 60


def dimensional_ttl_schedule() -> TtlSchedule:
    # The jobs cover UTC days, so the TTL bands must start at UTC midnight too. With bands in the
    # team timezone, the current UTC day moves into the 1-day band when the team's local day
    # starts, and that day then stops refreshing until the next UTC midnight. The band cutoffs are
    # relative to now, so build the schedule per call.
    return parse_ttl_schedule(
        DIMENSIONAL_TTL_SECONDS, "UTC", default_ttl_jitter_seconds=DIMENSIONAL_DEFAULT_TTL_JITTER_SECONDS
    )


# Per-session row, then aggregated into hourly buckets. `host`/`device_type`/
# `pathname`/`browser`/`os`/`viewport_*`/geoip are event-level group keys; the
# remaining dimensions are session-level and pulled via `any(session.…)`.
STATS_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS period_bucket,
    host AS host,
    device_type AS device_type,
    pathname AS pathname,
    entry_pathname AS entry_pathname,
    end_pathname AS end_pathname,
    browser AS browser,
    os AS os,
    viewport_width AS viewport_width,
    viewport_height AS viewport_height,
    referring_domain AS referring_domain,
    utm_source AS utm_source,
    utm_medium AS utm_medium,
    utm_campaign AS utm_campaign,
    utm_term AS utm_term,
    utm_content AS utm_content,
    country_code AS country_code,
    city_name AS city_name,
    region_code AS region_code,
    region_name AS region_name,
    has_gclid AS has_gclid,
    has_gad_source_paid_search AS has_gad_source_paid_search,
    has_fbclid AS has_fbclid,
    mat_metadata_backend AS mat_metadata_backend,
    mat_metadata_loggedIn AS mat_metadata_loggedIn,
    channel_type AS channel_type,
    uniqState(session_person_id) AS persons_uniq_state,
    uniqState(session_id) AS sessions_uniq_state,
    sumState(pageview_count) AS pageviews_count_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        events.$session_id AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        events.properties.$host AS host,
        events.properties.$device_type AS device_type,
        events.properties.$pathname AS pathname,
        events.properties.$browser AS browser,
        events.properties.$os AS os,
        toIntOrZero(toString(events.properties.$viewport_width)) AS viewport_width,
        toIntOrZero(toString(events.properties.$viewport_height)) AS viewport_height,
        events.properties.$geoip_country_code AS country_code,
        events.properties.$geoip_city_name AS city_name,
        events.properties.$geoip_subdivision_1_code AS region_code,
        events.properties.$geoip_subdivision_1_name AS region_name,
        any(session.$entry_pathname) AS entry_pathname,
        any(session.$end_pathname) AS end_pathname,
        any(session.$entry_referring_domain) AS referring_domain,
        any(session.$entry_utm_source) AS utm_source,
        any(session.$entry_utm_medium) AS utm_medium,
        any(session.$entry_utm_campaign) AS utm_campaign,
        any(session.$entry_utm_term) AS utm_term,
        any(session.$entry_utm_content) AS utm_content,
        any(and(notEmpty(coalesce(session.$entry_gclid, '')), notEquals(coalesce(session.$entry_gclid, ''), 'null'))) AS has_gclid,
        any(equals(coalesce(session.$entry_gad_source, ''), '1')) AS has_gad_source_paid_search,
        any(and(notEmpty(coalesce(session.$entry_fbclid, '')), notEquals(coalesce(session.$entry_fbclid, ''), 'null'))) AS has_fbclid,
        {mat_logged_in_inner} AS mat_metadata_loggedIn,
        {mat_backend_inner} AS mat_metadata_backend,
        any(session.$channel_type) AS channel_type,
        assumeNotNull(toInt(countIf(or(equals(events.event, '$pageview'), equals(events.event, '$screen'))))) AS pageview_count
    FROM events
    WHERE and(
        events.$session_id IS NOT NULL,
        or(equals(events.event, '$pageview'), equals(events.event, '$screen')),
        events.timestamp >= {time_window_min},
        events.timestamp < ({time_window_max} + toIntervalMinute({pad_minutes}))
    )
    GROUP BY
        session_id,
        host,
        device_type,
        pathname,
        browser,
        os,
        viewport_width,
        viewport_height,
        country_code,
        city_name,
        region_code,
        region_name
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY
    period_bucket,
    host,
    device_type,
    pathname,
    entry_pathname,
    end_pathname,
    browser,
    os,
    viewport_width,
    viewport_height,
    referring_domain,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    country_code,
    city_name,
    region_code,
    region_name,
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid,
    mat_metadata_backend,
    mat_metadata_loggedIn,
    channel_type
"""


# Bounces are attributed per session (no pathname dimension). The inner query
# collapses to one row per session and reads the session's computed `$is_bounce`
# / `$session_duration`; the outer query sums them into hourly buckets.
BOUNCES_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS period_bucket,
    host AS host,
    device_type AS device_type,
    entry_pathname AS entry_pathname,
    end_pathname AS end_pathname,
    browser AS browser,
    os AS os,
    viewport_width AS viewport_width,
    viewport_height AS viewport_height,
    referring_domain AS referring_domain,
    utm_source AS utm_source,
    utm_medium AS utm_medium,
    utm_campaign AS utm_campaign,
    utm_term AS utm_term,
    utm_content AS utm_content,
    country_code AS country_code,
    city_name AS city_name,
    region_code AS region_code,
    region_name AS region_name,
    has_gclid AS has_gclid,
    has_gad_source_paid_search AS has_gad_source_paid_search,
    has_fbclid AS has_fbclid,
    mat_metadata_backend AS mat_metadata_backend,
    mat_metadata_loggedIn AS mat_metadata_loggedIn,
    channel_type AS channel_type,
    uniqState(session_person_id) AS persons_uniq_state,
    uniqState(session_id) AS sessions_uniq_state,
    sumState(pageview_count) AS pageviews_count_state,
    sumState(assumeNotNull(toInt(ifNull(is_bounce, 0)))) AS bounces_count_state,
    sumState(session_duration) AS total_session_duration_state,
    sumState(assumeNotNull(toInt(1))) AS total_session_count_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        events.$session_id AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        any(events.properties.$host) AS host,
        any(events.properties.$device_type) AS device_type,
        any(events.properties.$browser) AS browser,
        any(events.properties.$os) AS os,
        toIntOrZero(toString(any(events.properties.$viewport_width))) AS viewport_width,
        toIntOrZero(toString(any(events.properties.$viewport_height))) AS viewport_height,
        any(events.properties.$geoip_country_code) AS country_code,
        any(events.properties.$geoip_city_name) AS city_name,
        any(events.properties.$geoip_subdivision_1_code) AS region_code,
        any(events.properties.$geoip_subdivision_1_name) AS region_name,
        any(session.$entry_pathname) AS entry_pathname,
        any(session.$end_pathname) AS end_pathname,
        any(session.$entry_referring_domain) AS referring_domain,
        any(session.$entry_utm_source) AS utm_source,
        any(session.$entry_utm_medium) AS utm_medium,
        any(session.$entry_utm_campaign) AS utm_campaign,
        any(session.$entry_utm_term) AS utm_term,
        any(session.$entry_utm_content) AS utm_content,
        any(and(notEmpty(coalesce(session.$entry_gclid, '')), notEquals(coalesce(session.$entry_gclid, ''), 'null'))) AS has_gclid,
        any(equals(coalesce(session.$entry_gad_source, ''), '1')) AS has_gad_source_paid_search,
        any(and(notEmpty(coalesce(session.$entry_fbclid, '')), notEquals(coalesce(session.$entry_fbclid, ''), 'null'))) AS has_fbclid,
        {mat_logged_in_inner} AS mat_metadata_loggedIn,
        {mat_backend_inner} AS mat_metadata_backend,
        any(session.$channel_type) AS channel_type,
        any(session.$is_bounce) AS is_bounce,
        assumeNotNull(toInt(any(session.$session_duration))) AS session_duration,
        assumeNotNull(toInt(countIf(or(equals(events.event, '$pageview'), equals(events.event, '$screen'))))) AS pageview_count
    FROM events
    WHERE and(
        events.$session_id IS NOT NULL,
        or(equals(events.event, '$pageview'), equals(events.event, '$screen')),
        events.timestamp >= {time_window_min},
        events.timestamp < ({time_window_max} + toIntervalMinute({pad_minutes}))
    )
    GROUP BY session_id
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY
    period_bucket,
    host,
    device_type,
    entry_pathname,
    end_pathname,
    browser,
    os,
    viewport_width,
    viewport_height,
    referring_domain,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    country_code,
    city_name,
    region_code,
    region_name,
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid,
    mat_metadata_backend,
    mat_metadata_loggedIn,
    channel_type
"""


def _mat_metadata_placeholders() -> dict[str, ast.Expr]:
    """Build the EU/US `mat_metadata_*` placeholder expressions.

    On EU the custom metadata is a materialized event property, aggregated per
    session-group with `any()` (mirroring v2). On US these columns are always
    NULL, typed so the INSERT into the Nullable columns succeeds.
    """
    if not is_eu_cluster():
        # Typed NULLs without a CAST (HogQL rejects `CAST(NULL AS Nullable(...))`):
        # `if(false, <typed literal>, NULL)` yields Nullable(Bool)/Nullable(String).
        return {
            "mat_logged_in_inner": parse_expr("if(1 = 0, true, NULL)"),
            "mat_backend_inner": parse_expr("if(1 = 0, '', NULL)"),
        }

    return {
        "mat_logged_in_inner": parse_expr(
            "any(if(events.properties.`metadata.loggedIn` IS NULL, NULL, equals(events.properties.`metadata.loggedIn`, 'true')))"
        ),
        "mat_backend_inner": parse_expr("any(events.properties.`metadata.backend`)"),
    }


def _base_placeholders() -> dict[str, ast.Expr]:
    return {
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
        **_mat_metadata_placeholders(),
    }


# Same ceilings as the legacy pre-aggregation job (`WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS`), whose
# tables these replace. One UTC day of a very large team's events, grouped by every fixed dimension,
# outgrows the default 42 GiB limit in the step that merges the shards' partial aggregates.
DIMENSIONAL_INSERT_SETTINGS: dict[str, int | str] = {
    "max_memory_usage": 140 * 1024**3,
    "max_bytes_before_external_group_by": 70 * 1024**3,
    "distributed_aggregation_memory_efficient": 1,
    "max_execution_time": 2200,
    # Spread the sessions-table reads over every replica, like the legacy job. `in_order` sends every
    # one of these heavy reads to the first replica.
    "load_balancing": "random",
}

# HogQL filters the sessions table by the time in the session id, which comes from the device
# clock, while event timestamps are corrected at capture. A device clock that runs slow gives a
# session id earlier than the session's real start, so the buffer is the clock skew we tolerate.
# 25 hours matches the legacy pre-aggregation job and avoids the default 3 days on each side,
# which makes these inserts read about twice as many sessions.
DIMENSIONAL_SESSION_BUFFER_MINUTES = 25 * 60


# Modifier fields that change what the INSERTs store. The executor leaves modifiers out of the job
# hash, so `dimensional_cache_key_context` adds these values to it: a team settings change gives new
# jobs, and the old ones stop matching. A read whose values differ from the team's cannot use the jobs.
DIMENSIONAL_SEMANTIC_MODIFIER_FIELDS: tuple[str, ...] = (
    "bounceRateDurationSeconds",
    "bounceRatePageViewMode",
    "customChannelTypeRules",
    "materializationMode",
    "personsOnEventsMode",
    "sessionsV2JoinMode",
    "sessionTableVersion",
)


# The sessions v3 table holds every session only from the day its backfill reached, per Cloud region.
# A region missing here has no complete v3 history yet, so a v3 team there gets no dimensional days.
SESSIONS_V3_COVERAGE_START_BY_REGION: dict[str, datetime] = {
    "US": datetime(2026, 10, 1, tzinfo=UTC),
}
_NO_SESSIONS_COVERAGE = datetime.max.replace(tzinfo=UTC)


def sessions_coverage_floor(modifiers: HogQLQueryModifiers) -> datetime | None:
    # A window before the floor builds as if no sessions existed: empty for the stats template, and
    # without entry dimensions or bounces for the rest. The writer must not build it and reads must
    # not serve it. Off Cloud the v3 materialized view fills the table natively, so it has no floor.
    if modifiers.sessionTableVersion != SessionTableVersion.V3 or not is_cloud():
        return None
    region = (settings.CLOUD_DEPLOYMENT or "").upper()
    return SESSIONS_V3_COVERAGE_START_BY_REGION.get(region, _NO_SESSIONS_COVERAGE)


def dimensional_insert_modifiers(team: Team) -> HogQLQueryModifiers:
    return create_default_modifiers_for_team(
        team, HogQLQueryModifiers(sessionTimestampBufferMinutes=DIMENSIONAL_SESSION_BUFFER_MINUTES)
    )


def dimensional_cache_key_context(modifiers: HogQLQueryModifiers) -> dict[str, str]:
    dump = modifiers.model_dump(mode="json")
    return {
        "semantic_modifiers": json.dumps(
            {field: dump.get(field) for field in DIMENSIONAL_SEMANTIC_MODIFIER_FIELDS}, sort_keys=True
        )
    }


def ensure_web_stats_dimensional_precomputed(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
    run_inserts: bool = True,
    stale_while_revalidate_seconds: float | None = None,
    modifiers: HogQLQueryModifiers | None = None,
) -> LazyComputationResult:
    modifiers = modifiers or dimensional_insert_modifiers(team)
    return ensure_precomputed(
        team=team,
        insert_query=STATS_INSERT_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=dimensional_ttl_schedule(),
        table=LazyComputationTable.WEB_STATS_DIMENSIONAL_PREAGGREGATED,
        placeholders=_base_placeholders(),
        query_type="web_stats_dimensional_insert",
        # Readers select by job_id as soon as a job turns READY, so its rows must be on the replica quorum first.
        read_after_write=True,
        run_inserts=run_inserts,
        stale_while_revalidate_seconds=stale_while_revalidate_seconds,
        insert_settings=DIMENSIONAL_INSERT_SETTINGS,
        modifiers=modifiers,
        cache_key_context=dimensional_cache_key_context(modifiers),
    )


def ensure_web_bounces_dimensional_precomputed(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
    run_inserts: bool = True,
    stale_while_revalidate_seconds: float | None = None,
    modifiers: HogQLQueryModifiers | None = None,
) -> LazyComputationResult:
    modifiers = modifiers or dimensional_insert_modifiers(team)
    return ensure_precomputed(
        team=team,
        insert_query=BOUNCES_INSERT_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=dimensional_ttl_schedule(),
        table=LazyComputationTable.WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED,
        placeholders=_base_placeholders(),
        query_type="web_bounces_dimensional_insert",
        # Readers select by job_id as soon as a job turns READY, so its rows must be on the replica quorum first.
        read_after_write=True,
        run_inserts=run_inserts,
        stale_while_revalidate_seconds=stale_while_revalidate_seconds,
        insert_settings=DIMENSIONAL_INSERT_SETTINGS,
        modifiers=modifiers,
        cache_key_context=dimensional_cache_key_context(modifiers),
    )


# The hourly writer rebuilds today's window, and the read keeps serving the previous
# generation while the rebuild runs or after a run fails. The grace stays far below
# EXPIRY_BUFFER_SECONDS, so the ClickHouse rows of a graced job still exist.
DIMENSIONAL_READ_STALE_WHILE_REVALIDATE_SECONDS = 30 * 60


@frozen
class DimensionalJobIds:
    # None for a table the caller did not ask for.
    stats: list[UUID] | None
    bounces: list[UUID] | None
    stale: bool = False
    # The oldest `computed_at` of the served jobs.
    computed_at: datetime | None = None


def dimensional_job_ids(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
    tables: Collection[str],
    modifiers: HogQLQueryModifiers,
) -> DimensionalJobIds | None:
    """Return the READY job ids of `tables` that cover the range, or None when any of them
    has a gap. Check-only: a read never builds a window, the scheduled job does.
    The framework splits jobs on UTC days, so the bounds should already be in UTC."""
    results: dict[str, LazyComputationResult] = {}
    ensure_by_table = {
        WEB_STATS_DIMENSIONAL_READ_TABLE: ensure_web_stats_dimensional_precomputed,
        WEB_BOUNCES_DIMENSIONAL_READ_TABLE: ensure_web_bounces_dimensional_precomputed,
    }
    for table, ensure in ensure_by_table.items():
        if table not in tables:
            continue
        result = ensure(
            team,
            time_range_start,
            time_range_end,
            run_inserts=False,
            stale_while_revalidate_seconds=DIMENSIONAL_READ_STALE_WHILE_REVALIDATE_SECONDS,
            modifiers=modifiers,
        )
        if not result.ready:
            return None
        results[table] = result

    stats = results.get(WEB_STATS_DIMENSIONAL_READ_TABLE)
    bounces = results.get(WEB_BOUNCES_DIMENSIONAL_READ_TABLE)
    return DimensionalJobIds(
        stats=stats.job_ids if stats else None,
        bounces=bounces.job_ids if bounces else None,
        stale=any(result.stale for result in results.values()),
        computed_at=min(
            (result.computed_at for result in results.values() if result.computed_at is not None), default=None
        ),
    )
