# Session metrics from the events table alone, grouped by `$session_id`, with no sessions-table or
# person-overrides join: the sessions join cannot be shard-local, because the two tables are sharded
# by different keys on different clusters. Bounce mirrors sessions v3 over every event of the
# session, and `start_timestamp` is the UUIDv7 millisecond timestamp the sessions table keys on, so
# period attribution agrees with the join path while duration, entry and exit page only see events
# inside the scanned range.
SESSIONLESS_SESSIONS_QUERY = """
SELECT
    events.$session_id AS session_id,
    any(events.person_id) AS person_id,
    countIf(or(events.event = '$pageview', events.event = '$screen')) AS page_screen_count,
    max(events.event = '$autocapture') AS has_autocapture,
    dateDiff('second', min(events.timestamp), max(events.timestamp)) AS session_duration,
    argMinIf(events.properties.$pathname, events.timestamp, or(events.event = '$pageview', events.event = '$screen')) AS entry_pathname,
    argMaxIf(events.properties.$pathname, events.timestamp, or(events.event = '$pageview', events.event = '$screen')) AS exit_pathname,
    argMinIf(events.properties.$host, events.timestamp, or(events.event = '$pageview', events.event = '$screen')) AS entry_host,
    argMaxIf(events.properties.$host, events.timestamp, or(events.event = '$pageview', events.event = '$screen')) AS exit_host,
    fromUnixTimestamp(intDiv(toInt(bitShiftRight(any(events.$session_id_uuid), 80)), 1000)) AS start_timestamp,
    if(page_screen_count = 0, NULL, not(or(
        page_screen_count >= 2,
        has_autocapture,
        session_duration >= {bounce_rate_duration_seconds}
    ))) AS is_bounce
FROM events
WHERE and(
    {events_session_id_present},
    {inside_timestamp_periods},
    {event_filters},
)
GROUP BY session_id
HAVING page_screen_count > 0
"""

# Column order matches the join and two-scan shapes, which `WebOverviewQueryRunner._calculate`
# indexes positionally. Views count the pageviews of sessions that start in the period.
SESSIONLESS_OVERVIEW_QUERY = """
SELECT
    uniqIf(s.person_id, {current_period}) AS unique_users,
    {previous_unique_users} AS previous_unique_users,
    sumIf(s.page_screen_count, {current_period}) AS total_filtered_pageview_count,
    {previous_total_filtered_pageview_count} AS previous_total_filtered_pageview_count,
    countIf({current_period}) AS unique_sessions,
    {previous_unique_sessions} AS previous_unique_sessions,
    avgIf(s.session_duration, {current_period}) AS avg_duration_s,
    {previous_avg_duration_s} AS previous_avg_duration_s,
    avgIf(s.is_bounce, {current_period}) AS bounce_rate,
    {previous_bounce_rate} AS previous_bounce_rate
FROM {sessions} AS s
"""

# PAGE breakdown with bounce rate: the counts side is the same events scan as the no-join shape;
# the bounce side reads the per-session rows instead of the sessions table.
SESSIONLESS_PATH_BOUNCE_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
FROM (
    SELECT
        {breakdown_value} AS breakdown_value,
        uniqIf(events.person_id, {current_timestamp_period}) AS visitors,
        uniqIf(events.person_id, {previous_timestamp_period}) AS previous_visitors,
        countIf({current_timestamp_period}) AS views,
        countIf({previous_timestamp_period}) AS previous_views
    FROM events
    WHERE and(
        {events_session_id_present},
        or(events.event == '$pageview', events.event == '$screen'),
        {inside_timestamp_periods},
        {event_filters},
    )
    GROUP BY breakdown_value
) AS counts
LEFT JOIN (
    SELECT
        {bounce_breakdown_value} AS breakdown_value,
        avgIf(s.is_bounce, {current_session_period}) AS bounce_rate,
        avgIf(s.is_bounce, {previous_session_period}) AS previous_bounce_rate
    FROM {sessions} AS s
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

SESSIONLESS_PATH_BOUNCE_AND_AVG_TIME_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",

    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",

    tuple(
        coalesce(time_on_page.avg_time_on_page, 0),
        coalesce(time_on_page.previous_avg_time_on_page, 0)
    ) AS "context.columns.avg_time_on_page",

    tuple(
        coalesce(bounce.bounce_rate, 0),
        coalesce(bounce.previous_bounce_rate, 0)
    ) AS "context.columns.bounce_rate"

FROM (
    SELECT
        {breakdown_value} AS breakdown_value,
        uniqIf(events.person_id, {current_timestamp_period}) AS visitors,
        uniqIf(events.person_id, {previous_timestamp_period}) AS previous_visitors,
        countIf({current_timestamp_period}) AS views,
        countIf({previous_timestamp_period}) AS previous_views
    FROM events
    WHERE and(
        {events_session_id_present},
        or(events.event == '$pageview', events.event == '$screen'),
        {inside_timestamp_periods},
        {event_filters},
    )
    GROUP BY breakdown_value
) AS counts

LEFT JOIN (
    SELECT
        {time_on_page_breakdown_value} AS breakdown_value,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {current_timestamp_period}
        ) AS avg_time_on_page,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {previous_timestamp_period}
        ) AS previous_avg_time_on_page
    FROM events
    WHERE and(
        or(events.event = '$pageview', events.event = '$pageleave', events.event = '$screen'),
        {time_on_page_breakdown_value} IS NOT NULL,
        events.properties.`$prev_pageview_duration` IS NOT NULL,
        {inside_timestamp_periods},
        {time_on_page_filters},
    )
    GROUP BY breakdown_value
) AS time_on_page
ON counts.breakdown_value = time_on_page.breakdown_value

LEFT JOIN (
    SELECT
        {bounce_breakdown_value} AS breakdown_value,
        avgIf(s.is_bounce, {current_session_period}) AS bounce_rate,
        avgIf(s.is_bounce, {previous_session_period}) AS previous_bounce_rate
    FROM {sessions} AS s
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

# Entry and exit page breakdowns: one row per session from the per-session rows, in the column
# layout of MAIN_INNER_QUERY so the simple-breakdown outer query is reused unchanged.
SESSIONLESS_ENTRY_EXIT_INNER_QUERY = """
SELECT
    s.person_id AS filtered_person_id,
    s.page_screen_count AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    s.session_id AS session_id,
    s.is_bounce AS is_bounce,
    s.start_timestamp AS start_timestamp
FROM {sessions} AS s
"""
