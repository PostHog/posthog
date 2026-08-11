import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { HogQLQueryString, hogql } from '~/queries/utils'

// Emitted once per run when the run starts, but only for workflows with a conversion goal — so the
// absence of these events means "no goal configured", not "nobody enrolled".
const ENROLLED_EVENT = '$workflows_enrolled'
const CONVERSION_EVENT = '$workflows_conversion'

export type WorkflowConversionRequest = {
    workflowId: string
    dateFrom: string
    dateTo: string
    interval: 'day' | 'hour' | 'minute'
    // null means no window: a run counts as converted whenever the conversion lands, however long after.
    windowMinutes: number | null
}

export type WorkflowConversionSeries = {
    labels: string[]
    // Runs that started in each bucket, and how many of those went on to convert. Both are keyed on
    // the bucket the run STARTED in, not the bucket it converted in — that's what makes a bucket's
    // rate answerable ("of the runs started that day, how many converted?").
    enrolled: number[]
    converted: number[]
}

// Conversions are counted by pairing each run's enrollment with its conversion on `$workflow_run_id`,
// rather than by counting conversion events as they stream in. That's what lets a conversion count
// after the run has already finished: by then the run's cyclotron job is gone, so the live pipeline
// has nothing left to match against, but the events are still in ClickHouse.
//
// Bucketing mirrors `loadAppMetricsTimeSeries` (calendar padding, DST-safe stepping) so these series
// line up with the app-metric series they sit next to in the summary chart.
export async function loadWorkflowConversionSeries(
    request: WorkflowConversionRequest,
    timezone: string
): Promise<WorkflowConversionSeries> {
    const { interval } = request

    // The conversion side is deliberately not bounded above: a run that started at the very end of
    // the range may convert after it, and that conversion belongs to the run's starting bucket.
    // Runs are deduped by `$workflow_run_id` first, so a retry that re-emits an enrollment event
    // (possible if a run errors before its state persists) still counts as one run.
    // Interpolated raw because the `hogql` tag would otherwise quote the fragment as a string
    // literal. Safe: the only interpolated value is coerced to an integer here.
    const windowMinutes = Number.isFinite(request.windowMinutes) ? Math.floor(request.windowMinutes as number) : null
    const windowClause = hogql.raw(
        windowMinutes && windowMinutes > 0 ? `AND converted_at <= enrolled_at + toIntervalMinute(${windowMinutes})` : ''
    )

    const query = hogql`
        WITH
            ${timezone} AS tz,
            ${interval} AS g,

            toDateTime(${request.dateFrom}, tz) AS from_local,
            toDateTime(${request.dateTo},   tz) AS to_local,

            dateTrunc(g, from_local, tz) AS start_bucket,
            dateTrunc(g, to_local,   tz) AS end_bucket,

            multiIf(
                g = 'minute', dateDiff('minute', start_bucket, end_bucket) + 1,
                g = 'hour',   dateDiff('hour',   start_bucket, end_bucket) + 1,
                g = 'day',    dateDiff('day',    start_bucket, end_bucket) + 1,
                0
            ) AS steps,

            arrayMap(n ->
                multiIf(
                    g = 'minute', addMinutes(start_bucket, n),
                    g = 'hour',   addHours(start_bucket, n),
                    g = 'day',    addDays(start_bucket, n),
                    start_bucket
                ),
                range(0, steps)
            ) AS calendar,

            multiIf(
                g = 'minute', addMinutes(end_bucket, 1),
                g = 'hour',   addHours(end_bucket,   1),
                g = 'day',    addDays(end_bucket,    1),
                end_bucket
            ) AS end_exclusive

        SELECT
            calendar AS date,
            arrayMap(d -> if(indexOf(buckets, d) = 0, 0, enrolled_counts[indexOf(buckets, d)]), calendar) AS enrolled,
            arrayMap(d -> if(indexOf(buckets, d) = 0, 0, converted_counts[indexOf(buckets, d)]), calendar) AS converted
        FROM
        (
            SELECT
                groupArray(bucket)        AS buckets,
                groupArray(enrolled_cnt)  AS enrolled_counts,
                groupArray(converted_cnt) AS converted_counts
            FROM
            (
                SELECT
                    dateTrunc(g, toTimeZone(enrolled_at, tz), tz) AS bucket,
                    count() AS enrolled_cnt,
                    countIf(converted_at >= enrolled_at ${windowClause}) AS converted_cnt
                FROM
                (
                    SELECT
                        properties.$workflow_run_id AS run_id,
                        minIf(timestamp, event = ${ENROLLED_EVENT}) AS enrolled_at,
                        minIf(timestamp, event = ${CONVERSION_EVENT}) AS converted_at
                    FROM events
                    WHERE event IN (${ENROLLED_EVENT}, ${CONVERSION_EVENT})
                        AND properties.$workflow_id = ${request.workflowId}
                        AND properties.$workflow_run_id != ''
                        AND toTimeZone(timestamp, tz) >= start_bucket
                    GROUP BY run_id
                    -- Drop runs whose enrollment falls outside the range: a conversion alone (from a
                    -- run that started earlier) must not invent a denominator row it has no start for.
                    HAVING enrolled_at > toDateTime(0)
                        AND toTimeZone(enrolled_at, tz) < end_exclusive
                )
                GROUP BY bucket
                ORDER BY bucket
            )
        )
    ` as HogQLQueryString

    const response = await api.queryHogQL(
        query,
        { scene: 'Workflow', productKey: 'messaging' },
        { refresh: 'force_blocking' }
    )

    const row = response.results?.[0]
    if (!row) {
        return { labels: [], enrolled: [], converted: [] }
    }

    const labels = (row[0] as string[]).map((label) =>
        dayjs(label)
            .tz(timezone)
            .format(interval === 'day' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm')
    )

    return { labels, enrolled: row[1] ?? [], converted: row[2] ?? [] }
}
