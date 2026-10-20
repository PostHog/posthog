// Matches the check's window on the server, so the query lists the same repeats the check counted.
const REPEAT_WINDOW_MILLISECONDS = 100

export interface RepeatedEventsScope {
    events: string[]
    dateFrom: string
    dateTo: string
    sampleRate: number
}

function sqlString(value: string): string {
    return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

export function repeatedEventsQueryOf({ events, dateFrom, dateTo, sampleRate }: RepeatedEventsScope): string {
    const eventFilter = events.length ? `event IN (${events.map(sqlString).join(', ')}) AND ` : ''
    const sample = sampleRate < 1 ? ` SAMPLE ${Number(sampleRate.toPrecision(3))}` : ''
    // The partition matches the check's, so an event counts as a repeat only when nothing but its time differs.
    return `-- Events sent again by the same person less than ${REPEAT_WINDOW_MILLISECONDS} ms apart, on the days the check read
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
                PARTITION BY
                    distinct_id,
                    event,
                    properties.$raw_user_agent,
                    properties.$current_url,
                    properties.$screen_name,
                    properties.$feature_flag,
                    properties.$event_type,
                    elements_chain_texts,
                    elements_chain_href,
                    elements_chain_ids,
                    elements_chain_elements
                ORDER BY timestamp
                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ),
            timestamp
        ) AS milliseconds_after_previous
    FROM events${sample}
    WHERE ${eventFilter}toDate(timestamp) >= toDate(${sqlString(dateFrom)}) AND toDate(timestamp) <= toDate(${sqlString(dateTo)})
)
WHERE milliseconds_after_previous < ${REPEAT_WINDOW_MILLISECONDS}
ORDER BY timestamp DESC
LIMIT 100`
}
