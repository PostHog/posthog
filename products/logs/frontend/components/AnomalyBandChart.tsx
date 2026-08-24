import { useCallback, useMemo } from 'react'

import {
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    DefaultTooltip,
    TimeSeriesLineChart,
    type AnomalyMarker,
    type DateRangeZoomData,
    type PointClickData,
    type Series,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { LogsAnomalyScanBucketApi, LogsAnomalyVerdictEnumApi } from 'products/logs/frontend/generated/api.schemas'
import type { ScanRange } from 'products/logs/frontend/logsAnomaliesLogic'

const OBSERVED_KEY = 'observed'

export interface BandChartData {
    labels: string[]
    observed: number[]
    lower: number[]
    upper: number[]
    verdicts: (LogsAnomalyVerdictEnumApi | null)[]
}

// Band values stay NaN for unscored buckets so the chart shows a gap there. Coercing them to 0
// would render every unscored region as a drop to zero.
export function buildBandChartData(buckets: LogsAnomalyScanBucketApi[]): BandChartData {
    return {
        // Raw bucket times: the time axis formats the ticks, so it can switch to day boundaries on a
        // multi-day window without every label being baked at one width.
        labels: buckets.map((bucket) => bucket.time),
        observed: buckets.map((bucket) => bucket.observed),
        lower: buckets.map((bucket) => bucket.lower ?? NaN),
        upper: buckets.map((bucket) => bucket.upper ?? NaN),
        verdicts: buckets.map((bucket) => bucket.verdict),
    }
}

/** Matches the verdict tags above each chart, and follows the theme rather than pinning one shade. */
const VERDICT_POINT_COLOR: Record<LogsAnomalyVerdictEnumApi, string> = {
    spike: 'var(--danger)',
    drop: 'var(--warning)',
    silence: 'var(--danger-dark)',
}

/** Both indices name a bucket *start*, so the range has to run to the end of the last one. A range
 *  ending at its start would exclude the very bucket the user dragged over or clicked. Bucket width
 *  comes from the first gap rather than the scan's constant, so the two can't drift. */
export function bucketRange(
    buckets: LogsAnomalyScanBucketApi[],
    startIndex: number,
    endIndex: number
): ScanRange | null {
    const [from, to] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
    const start = buckets[from]?.time
    const end = buckets[to]?.time
    if (!start || !end || buckets.length < 2) {
        return null
    }
    const bucketMs = Date.parse(buckets[1].time) - Date.parse(buckets[0].time)
    if (!(bucketMs > 0)) {
        return null
    }
    return { dateFrom: start, dateTo: new Date(Date.parse(end) + bucketMs).toISOString() }
}

export interface AnomalyBandChartProps {
    buckets: LogsAnomalyScanBucketApi[]
    onZoom?: (range: ScanRange) => void
    onBucketClick?: (range: ScanRange) => void
}

export function AnomalyBandChart({ buckets, onZoom, onBucketClick }: AnomalyBandChartProps): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => buildBandChartData(buckets), [buckets])

    const series = useMemo<Series[]>(
        () => [{ key: OBSERVED_KEY, label: 'Observed', data: data.observed }],
        [data.observed]
    )

    // A verdict's color varies per bucket, which an area fill can't express, so the anomalous points
    // are their own overlay rather than a second series.
    const markers = useMemo<AnomalyMarker[]>(
        () =>
            buckets.flatMap((bucket, index) =>
                bucket.verdict
                    ? [
                          {
                              dataIndex: index,
                              value: bucket.observed,
                              color: VERDICT_POINT_COLOR[bucket.verdict],
                              yAxisId: DEFAULT_Y_AXIS_ID,
                          },
                      ]
                    : []
            ),
        [buckets]
    )

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            // Bucket times are UTC, and the scan's own timestamps around this chart render in the
            // viewer's zone, so the axis reads there too. The scan buckets at a fixed few minutes.
            xAxis: { timezone: dayjs.tz.guess(), interval: 'minute' },
            yAxis: { tickFormatter: humanFriendlyNumber },
            confidenceIntervals: [{ seriesKey: OBSERVED_KEY, lower: data.lower, upper: data.upper }],
        }),
        [data.lower, data.upper]
    )

    const onDateRangeZoom = useMemo(
        () =>
            onZoom
                ? ({ startIndex, endIndex }: DateRangeZoomData) => {
                      const range = bucketRange(buckets, startIndex, endIndex)
                      if (range) {
                          onZoom(range)
                      }
                  }
                : undefined,
        [buckets, onZoom]
    )

    const onPointClick = useMemo(
        () =>
            onBucketClick
                ? ({ dataIndex }: PointClickData) => {
                      const range = bucketRange(buckets, dataIndex, dataIndex)
                      if (range) {
                          onBucketClick(range)
                      }
                  }
                : undefined,
        [buckets, onBucketClick]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => {
            const bucket = buckets[ctx.dataIndex]
            const verdict = bucket?.verdict
            return (
                <DefaultTooltip
                    {...ctx}
                    labelFormatter={(label) => dayjs(label).format('MMM D, HH:mm')}
                    valueFormatter={(value) => `${humanFriendlyNumber(value)}${verdict ? ` (${verdict})` : ''}`}
                    footer={bucket ? bandSummary(bucket) : null}
                />
            )
        },
        [buckets]
    )

    return (
        // Quill chart roots are `flex-1`, so the sized box has to be a flex column.
        <div className="h-40 w-full flex flex-col">
            <TimeSeriesLineChart
                series={series}
                labels={data.labels}
                theme={theme}
                config={config}
                tooltip={renderTooltip}
                onDateRangeZoom={onDateRangeZoom}
                onPointClick={onPointClick}
                dataAttr="logs-anomaly-band-chart"
            >
                <AnomalyPointsLayer markers={markers} radius={4} />
            </TimeSeriesLineChart>
        </div>
    )
}

function bandSummary(bucket: LogsAnomalyScanBucketApi): string {
    if (bucket.expected == null || bucket.lower == null || bucket.upper == null) {
        return 'Not scored'
    }
    return `Expected ${humanFriendlyNumber(bucket.expected)} (band ${humanFriendlyNumber(
        bucket.lower
    )} to ${humanFriendlyNumber(bucket.upper)})`
}
