"""Materialization of the session-grain table the attribution reads use.

One row per session, with the channel resolved here rather than on every read. That classifier is
what puts attribution on the sessions nodes: over 5.8M sessions, reading the ingredients costs
857 MiB and classifying them costs 4.24 GiB.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
    parse_ttl_schedule,
)

# Today's window refreshes hourly, the last two days daily, everything older is held for 90 days.
SESSIONS_TTL_SECONDS: dict[str, int] = {
    "0d": 60 * 60,
    "2d": 24 * 60 * 60,
    "default": 90 * 24 * 60 * 60,
}

# One INSERT per UTC day. The framework merges a fully-missing range into one INSERT, so without a
# cap a cold backfill scans the whole span at once.
CHUNK_DAYS = 1

# A session that starts just before a window's end still has events after it.
SESSION_FORWARD_PAD_MINUTES = 24 * 60

SESSIONS_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(min(events.session.$start_timestamp)) AS period_bucket,
    events.$session_id AS session_id,
    any(events.person_id) AS person_id,
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
    events.$session_id IS NOT NULL,
    equals(events.event, '$pageview'),
    events.timestamp >= {time_window_min},
    events.timestamp < ({time_window_max} + toIntervalMinute({pad_minutes}))
)
GROUP BY session_id
HAVING and(
    toStartOfHour(min(events.session.$start_timestamp)) >= {time_window_min},
    toStartOfHour(min(events.session.$start_timestamp)) < {time_window_max}
)
"""


def base_placeholders() -> dict[str, ast.Expr]:
    return {"pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES)}


def ensure_marketing_sessions_precomputed(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    return ensure_precomputed(
        team=team,
        insert_query=SESSIONS_INSERT_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=parse_ttl_schedule(SESSIONS_TTL_SECONDS, team.timezone, max_window_days=CHUNK_DAYS),
        table=LazyComputationTable.MARKETING_SESSIONS_DIMENSIONAL_PREAGGREGATED,
        placeholders=base_placeholders(),
        query_type="marketing_sessions_dimensional_insert",
    )
