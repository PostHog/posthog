# Paths tile queries for the screen view modes that read `$screen_name` as the path.
#
# The shared path-bounce queries key bounce rate by the session's `$entry_pathname` and read the
# session's `$is_bounce`. A session that starts on a `$screen` event has no entry pathname, and the
# default bounce definition is NULL for a session without `$pageview` events. These queries fall
# back to the first `$screen_name` of the session as the entry key and to a screen-count bounce.

SCREEN_FALLBACK_COUNTS_SUBQUERY = """
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
            {view_event_where},
            {inside_periods},
            {event_properties},
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
"""

# The entry key and the bounce value are per-session aggregates here, so the inner query groups by
# session only. `$entry_pathname` is constant within a session, which makes `any()` exact.
SCREEN_FALLBACK_BOUNCE_SUBQUERY = """
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            coalesce(
                nullIf(any({bounce_breakdown_value}), ''),
                argMinIf({screen_entry_value}, events.timestamp, isNotNull({screen_entry_value}))
            ) AS breakdown_value,
            any(coalesce(session.`$is_bounce`, {screen_is_bounce})) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            {view_event_where},
            {inside_periods},
            {bounce_event_properties},
            {session_properties}
        )
        GROUP BY session_id
    )
    GROUP BY breakdown_value
"""

SCREEN_FALLBACK_PATH_BOUNCE_QUERY = f"""
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
FROM ({SCREEN_FALLBACK_COUNTS_SUBQUERY}) AS counts
LEFT JOIN ({SCREEN_FALLBACK_BOUNCE_SUBQUERY}) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""

SCREEN_FALLBACK_PATH_BOUNCE_AND_AVG_TIME_QUERY = f"""
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
FROM ({SCREEN_FALLBACK_COUNTS_SUBQUERY}) AS counts
LEFT JOIN (
    SELECT
        {{time_on_page_breakdown_value}} AS breakdown_value,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {{avg_current_period}}
        ) AS avg_time_on_page,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {{avg_previous_period}}
        ) AS previous_avg_time_on_page
    FROM events
    WHERE and(
        or(events.event = '$pageleave', {{view_event_where}}),
        {{time_on_page_breakdown_value}} IS NOT NULL,
        events.properties.`$prev_pageview_duration` IS NOT NULL,
        {{inside_periods}},
        {{time_on_page_event_properties}},
        {{session_properties}}
    )
    GROUP BY breakdown_value
) AS time_on_page
ON counts.breakdown_value = time_on_page.breakdown_value
LEFT JOIN ({SCREEN_FALLBACK_BOUNCE_SUBQUERY}) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
WHERE counts.breakdown_value IS NOT NULL
"""
