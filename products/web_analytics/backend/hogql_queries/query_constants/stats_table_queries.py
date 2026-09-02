PATH_BOUNCE_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            {inside_periods},
            {event_properties},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            {inside_periods},
            {bounce_event_properties}, -- Using filtered properties but excluding pathname
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

PATH_BOUNCE_AND_AVG_TIME_QUERY = """
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
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event = '$pageview', events.event = '$screen'),
            {inside_periods},
            {event_properties},
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts

-- -----------------------------
-- Join: Avg Time on Page
-- -----------------------------
LEFT JOIN (
    SELECT
        {time_on_page_breakdown_value} AS breakdown_value,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {avg_current_period}
        ) AS avg_time_on_page,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {avg_previous_period}
        ) AS previous_avg_time_on_page
    FROM events
    WHERE and(
        or(events.event = '$pageview', events.event = '$pageleave', events.event = '$screen'),
        {time_on_page_breakdown_value} IS NOT NULL,
        events.properties.`$prev_pageview_duration` IS NOT NULL,
        {inside_periods},
        {time_on_page_event_properties},
        {session_properties}
    )
    GROUP BY breakdown_value
) AS time_on_page
ON counts.breakdown_value = time_on_page.breakdown_value

-- -----------------------------
-- Join: Bounce Rate
-- -----------------------------
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value,
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event = '$pageview', events.event = '$screen'),
            {inside_periods},
            {bounce_event_properties},
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

FRUSTRATION_METRICS_INNER_QUERY = """
SELECT
    any(person_id) AS filtered_person_id,
    countIf(events.event = '$pageview' OR events.event = '$screen') AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    countIf(events.event = '$exception') AS errors_count,
    countIf(events.event = '$rageclick') AS rage_clicks_count,
    countIf(events.event = '$dead_click') AS dead_clicks_count,
    session.session_id AS session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and({inside_periods}, {event_where}, {all_properties})
GROUP BY session_id, breakdown_value
"""

MAIN_INNER_QUERY = """
SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and({inside_periods}, {event_where}, {all_properties})
GROUP BY session_id, breakdown_value
"""

# Inner scan for the FirstPageview* breakdowns: one row per session, with the
# breakdown value computed from the session's earliest in-range $pageview/$screen.
# Two levels on purpose — the argMinIf aggregate must sit behind an alias so the
# breakdown expression compares plain subquery fields: a comparison whose subtree
# contains events.timestamp is treated as non-nullable by the printer's timestamp
# index optimization (see visit_compare_operation in posthog/hogql/printer/clickhouse.py),
# which turns the channel-type template's IS [NOT] NULL checks into dead
# `equals(x, NULL)` SQL. {first_pageview_properties} is a single argMinIf over a
# tuple, so every property comes from the same anchor event rather than each
# property independently skipping NULLs across different pageviews.
# Events without a usable session id are excluded ({session_id_present}): they
# can't be attributed to a session's first pageview, and GROUP BY session_id
# would otherwise merge them all into one arbitrary group. argMinIf only sees
# in-range events, so a session straddling date_from is attributed to its first
# *in-range* pageview — accepted drift vs the session-entry breakdowns at range edges.
FIRST_PAGEVIEW_INNER_QUERY = """
SELECT
    filtered_person_id,
    filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    session_id,
    is_bounce,
    start_timestamp
FROM (
    SELECT
        any(person_id) AS filtered_person_id,
        count() AS filtered_pageview_count,
        {first_pageview_properties} AS first_pageview_properties,
        session.session_id AS session_id,
        any(session.$is_bounce) AS is_bounce,
        min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and({inside_periods}, {event_where}, {all_properties}, {session_id_present})
    GROUP BY session_id
)
"""

# No-join variant of MAIN_INNER_QUERY for simple breakdowns that display no
# session-derived column (no bounce, no conversion goal, event-property
# breakdown value). The sessions join above contributes only `session_id`
# (grouping) and `$start_timestamp` (period attribution) in that case — both
# recoverable from the UUIDv7 session id itself, so the join is pure overhead
# (prod-measured 10x wall / ~400x memory on DeviceType for a large team).
# Sessionless and malformed-session-id events still count — the join keeps
# them too (NULL session row). Non-UUIDv7 ids are lumped under a NULL
# `session_id` (raw_sessions is v7-only, so the join's `session.session_id`
# is NULL for all of them) and get a NULL `start_timestamp`, which excludes
# them from compare-period buckets exactly as the join does. The outer query is
# unchanged. Unlike the PAGE no-join variants, filters need no special
# handling: with no sessions side, user and test-account filters apply inline
# to the single events scan.
NO_JOIN_MAIN_INNER_QUERY = """
SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    if(
        equals(bitAnd(bitShiftRight(events.$session_id_uuid, 76), 15), 7),
        events.$session_id,
        NULL
    ) AS session_id,
    any(if(
        equals(bitAnd(bitShiftRight(events.$session_id_uuid, 76), 15), 7),
        fromUnixTimestamp(intDiv(toInt(bitShiftRight(events.$session_id_uuid, 80)), 1000)),
        NULL
    )) AS start_timestamp
FROM events
WHERE and({inside_periods}, {event_where}, {all_properties})
GROUP BY session_id, breakdown_value
"""

# No-join variants of the PAGE-breakdown queries: counts come straight from events
# (bucketed by event timestamp) and bounce comes straight from the sessions table
# (bucketed by session start), instead of routing both through the events↔sessions
# lazy join. The join shape re-executes the sessions subquery on every shard of the
# events cluster, so for unfiltered queries these variants read ~10× fewer rows.
# The filter placeholders ({event_filters}, {bounce_sessions_filter},
# {time_on_page_filters}) are constant-true for the unfiltered no-join strategies;
# the session-id-set strategies fill them with events-side filters and a
# session-id IN filter so filtered queries share the same two-scan shape.
NO_JOIN_PATH_BOUNCE_QUERY = """
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
        avgIf(sessions.$is_bounce, {current_session_period}) AS bounce_rate,
        avgIf(sessions.$is_bounce, {previous_session_period}) AS previous_bounce_rate
    FROM sessions
    WHERE and(
        {inside_session_periods},
        or(sessions.$pageview_count > 0, sessions.$screen_count > 0),
        {bounce_sessions_filter},
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

NO_JOIN_PATH_BOUNCE_AND_AVG_TIME_QUERY = """
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
        avgIf(sessions.$is_bounce, {current_session_period}) AS bounce_rate,
        avgIf(sessions.$is_bounce, {previous_session_period}) AS previous_bounce_rate
    FROM sessions
    WHERE and(
        {inside_session_periods},
        or(sessions.$pageview_count > 0, sessions.$screen_count > 0),
        {bounce_sessions_filter},
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""
