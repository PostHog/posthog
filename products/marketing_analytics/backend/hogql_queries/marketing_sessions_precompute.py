"""Materialization of the session-grain table the attribution reads use.

One row per session, with the channel resolved here rather than on every read. That classifier is
what puts attribution on the sessions nodes: over 5.8M sessions, reading the ingredients costs
857 MiB and classifying them costs 4.24 GiB.
"""

import os
import hashlib
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import expand_default_channel_type_call

from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
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

SESSION_SETTLING_PERIOD_SECONDS = 24 * 60 * 60

# Bound the event scan by observed session ends; session IDs can span more than one day.
SESSIONS_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(min(events.session.$start_timestamp)) AS period_bucket,
    events.$session_id AS session_id,
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
    any(toString(ifNull(events.session.$entry_pathname, ''))) AS entry_pathname
FROM events
WHERE and(
    {classifier_version} = {classifier_version},
    events.$session_id IS NOT NULL,
    equals(events.event, '$pageview'),
    events.timestamp >= {time_window_min},
    events.timestamp <= (
        SELECT max($end_timestamp)
        FROM sessions
        WHERE toStartOfHour($start_timestamp) >= {time_window_min}
            AND toStartOfHour($start_timestamp) < {time_window_max}
    )
)
GROUP BY session_id, person_id
HAVING and(
    toStartOfHour(min(events.session.$start_timestamp)) >= {time_window_min},
    toStartOfHour(min(events.session.$start_timestamp)) < {time_window_max}
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
    return {"classifier_version": ast.Constant(value=f"{SESSION_CHANNEL_CLASSIFIER_VERSION}:{fingerprint}")}


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
        table=LazyComputationTable.MARKETING_SESSIONS_DIMENSIONAL_PREAGGREGATED,
        placeholders=base_placeholders(),
        query_type="marketing_sessions_dimensional_insert",
    )
