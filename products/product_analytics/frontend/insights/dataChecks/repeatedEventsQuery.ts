// Matches the check's window on the server, so the query lists the same repeats the check counted.
const REPEAT_WINDOW_MILLISECONDS = 100

function sqlString(value: string): string {
    return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

/** SQL for the SQL editor that lists each event sent again by the same person on the same page within the window. */
export function repeatedEventsQueryOf(events: string[], days: number): string {
    const eventFilter = events.length ? `event IN (${events.map(sqlString).join(', ')}) AND ` : ''
    return `-- Events sent again by the same person on the same page less than ${REPEAT_WINDOW_MILLISECONDS} ms apart
SELECT timestamp, event, distinct_id, url, library, library_version, milliseconds_after_previous
FROM (
    SELECT
        timestamp,
        event,
        distinct_id,
        properties.$current_url AS url,
        properties.$lib AS library,
        properties.$lib_version AS library_version,
        dateDiff(
            'millisecond',
            lagInFrame(timestamp) OVER (
                PARTITION BY distinct_id, event, properties.$current_url, properties.$screen_name
                ORDER BY timestamp
                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ),
            timestamp
        ) AS milliseconds_after_previous
    FROM events
    WHERE ${eventFilter}timestamp >= now() - INTERVAL ${days} DAY
)
WHERE milliseconds_after_previous < ${REPEAT_WINDOW_MILLISECONDS}
ORDER BY timestamp DESC
LIMIT 100`
}
