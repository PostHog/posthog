"""Materialize session touchpoints with their channel classified before attribution reads."""

import os
import hashlib
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import expand_default_channel_type_call
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.schema_enums import SessionTableVersion

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
    get_daily_windows,
    parse_ttl_schedule,
)

# Today's window refreshes hourly, the last two days daily, everything older is held for 90 days.
# The today band is two warmer periods wide: at one, it expires the minute the next run starts, so
# any delay in that run makes the window read as cold.
SESSIONS_TTL_SECONDS: dict[str, int] = {
    "0d": 2 * 60 * 60,
    "2d": 24 * 60 * 60,
    "default": 90 * 24 * 60 * 60,
}

# One INSERT per UTC day. The framework merges a fully-missing range into one INSERT, so without a
# cap a cold backfill scans the whole span at once.
CHUNK_DAYS = 1

# Display history; the shared window helper adds team lookback and session reachback.
PRECOMPUTE_WINDOW_DAYS = int(os.getenv("MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS", "90"))

# Bump for changes to the lookup dictionaries used by the builtin classifier.
SESSION_CHANNEL_CLASSIFIER_VERSION = 1
SESSION_READ_REACHBACK_DAYS = 1

MAX_PRECOMPUTED_SESSION_SECONDS = 3 * 24 * 60 * 60
SESSION_SETTLING_PERIOD_SECONDS = MAX_PRECOMPUTED_SESSION_SECONDS

# Keep start predicates unwrapped so the sessions resolver pushes them into raw sessions.
UNSUPPORTED_SESSIONS_QUERY = """
SELECT 1
FROM sessions
WHERE $start_timestamp >= {time_window_min}
    AND $start_timestamp < {time_window_max}
    AND $end_timestamp > $start_timestamp + toIntervalSecond({max_session_seconds})
LIMIT 1
"""

SESSIONS_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(toTimeZone(min(events.session.$start_timestamp), 'UTC')) AS period_bucket,
    events.$session_id_uuid AS session_id_v7,
    events.person_id AS person_id,
    min(events.session.$start_timestamp) AS start_timestamp,
    min(events.timestamp) AS min_event_timestamp,
    max(events.timestamp) AS max_event_timestamp,
    any(if(notEmpty(ifNull(events.session.$channel_type, '')), events.session.$channel_type, 'Unknown')) AS channel_type,
    any(toString(ifNull(events.session.$entry_utm_source, ''))) AS utm_source,
    any(toString(ifNull(events.session.$entry_utm_medium, ''))) AS utm_medium,
    any(toString(ifNull(events.session.$entry_utm_campaign, ''))) AS utm_campaign,
    any(toString(ifNull(events.session.$entry_utm_term, ''))) AS utm_term,
    any(toString(ifNull(events.session.$entry_utm_content, ''))) AS utm_content,
    any(toString(ifNull(events.session.$entry_referring_domain, ''))) AS referring_domain,
    any(toString(ifNull(events.session.$entry_pathname, ''))) AS entry_pathname,
    count() AS pageview_count
FROM events
WHERE and(
    {classifier_version} = {classifier_version},
    events.$session_id_uuid IS NOT NULL,
    equals(events.event, '$pageview'),
    events.timestamp >= {time_window_min},
    events.timestamp < {time_window_max} + toIntervalSecond({max_session_seconds})
)
GROUP BY session_id_v7, person_id
HAVING and(
    min(events.session.$start_timestamp) >= {time_window_min},
    min(events.session.$start_timestamp) < {time_window_max}
)
"""


def base_placeholders() -> dict[str, ast.Expr]:
    classifier = expand_default_channel_type_call(
        [
            ast.Field(chain=[name])
            for name in ("campaign", "medium", "source", "referring_domain", "has_gclid", "has_fbclid", "gad_source")
        ]
    )
    fingerprint = hashlib.sha256(classifier.to_hogql().encode()).hexdigest()
    # The executor hashes before resolving $channel_type, so carry its identity in the input AST.
    return {
        "classifier_version": ast.Constant(value=f"{SESSION_CHANNEL_CLASSIFIER_VERSION}:{fingerprint}"),
        "max_session_seconds": ast.Constant(value=MAX_PRECOMPUTED_SESSION_SECONDS),
    }


def precompute_window_days(team: Team) -> int:
    return (
        PRECOMPUTE_WINDOW_DAYS + team.marketing_analytics_config.attribution_window_days + SESSION_READ_REACHBACK_DAYS
    )


def ensure_marketing_sessions_precomputed(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
    *,
    run_inserts: bool = True,
    stale_while_revalidate_seconds: float | None = None,
) -> LazyComputationResult:
    modifiers = create_default_modifiers_for_team(team)
    if modifiers.sessionTableVersion == SessionTableVersion.V1:
        return LazyComputationResult(ready=False, job_ids=[], errors=["Session precompute requires sessions v2 or v3"])
    if modifiers.sessionTableVersion == SessionTableVersion.AUTO:
        modifiers.sessionTableVersion = SessionTableVersion.V2

    windows = get_daily_windows(time_range_start, time_range_end)
    if not windows:
        return LazyComputationResult(ready=True, job_ids=[])

    # Check cache hits too: a session can outgrow the scan budget after its window was materialized.
    unsupported = execute_hogql_query(
        UNSUPPORTED_SESSIONS_QUERY,
        team,
        modifiers=modifiers,
        query_type="marketing_sessions_precompute_coverage",
        placeholders={
            "time_window_min": ast.Constant(value=windows[0][0]),
            "time_window_max": ast.Constant(value=windows[-1][1]),
            "max_session_seconds": ast.Constant(value=MAX_PRECOMPUTED_SESSION_SECONDS),
        },
    )
    if unsupported.error:
        return LazyComputationResult(ready=False, job_ids=[], errors=["Could not verify session precompute coverage"])
    if unsupported.results:
        return LazyComputationResult(
            ready=False,
            job_ids=[],
            errors=["Session duration exceeds the precompute scan budget; use live attribution"],
        )

    return ensure_precomputed(
        run_inserts=run_inserts,
        stale_while_revalidate_seconds=stale_while_revalidate_seconds,
        team=team,
        insert_query=SESSIONS_INSERT_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        # Sessions opened inside a window keep evolving until they close, so a job computed while
        # the window was still settling must not freeze that snapshot for the whole band TTL.
        ttl_seconds=parse_ttl_schedule(
            SESSIONS_TTL_SECONDS,
            team.timezone,
            max_window_days=CHUNK_DAYS,
            settling_period_seconds=SESSION_SETTLING_PERIOD_SECONDS,
        ),
        table=LazyComputationTable.WEB_SESSIONS_DIMENSIONAL_PREAGGREGATED,
        modifiers=modifiers,
        cache_key_context={"modifiers": modifiers.model_dump_json(exclude_none=True)},
        placeholders=base_placeholders(),
        query_type="marketing_sessions_dimensional_insert",
    )
