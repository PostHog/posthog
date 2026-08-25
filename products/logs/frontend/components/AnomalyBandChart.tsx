import { useCallback, useMemo } from 'react'

import {
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    DefaultTooltip,
    TimeSeriesLineChart,
    type AnomalyMarker,
    type PointClickData,
    type Series,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { DateRange } from '~/queries/schema/schema-general'

import { selectedDateRange } from 'products/logs/frontend/components/LogsViewer/LogsViewerSparkline/bucketRanges'
import type { LogsSeriesBandBucketApi } from 'products/logs/frontend/generated/api.schemas'

const OBSERVED_KEY = 'observed'

export type OutOfBand = 'above' | 'below'

export interface BandChartData {
    labels: string[]
    observed: number[]
    lower: number[]
    upper: number[]
    outOfBand: (OutOfBand | null)[]
}

// Band values stay NaN for unbanded buckets so the chart shows a gap there. Coercing them to 0
// would render every unbanded region as a drop to zero.
export function buildBandChartData(buckets: LogsSeriesBandBucketApi[]): BandChartData {
    return {
        // Raw bucket times: the time axis formats the ticks, so it can switch to day boundaries on a
        // multi-day window without every label being baked at one width.
        labels: buckets.map((bucket) => bucket.time),
        observed: buckets.map((bucket) => bucket.observed),
        lower: buckets.map((bucket) => bucket.lower ?? NaN),
        upper: buckets.map((bucket) => bucket.upper ?? NaN),
        outOfBand: buckets.map((bucket) => {
            if (bucket.lower == null || bucket.upper == null) {
                return null
            }
            if (bucket.observed > bucket.upper) {
                return 'above'
            }
            if (bucket.observed < bucket.lower) {
                return 'below'
            }
            return null
        }),
    }
}

/** Follows the theme rather than pinning one shade. */
const OUT_OF_BAND_POINT_COLOR: Record<OutOfBand, string> = {
    above: 'var(--danger)',
    below: 'var(--warning)',
}

const OUT_OF_BAND_LABEL: Record<OutOfBand, string> = {
    above: 'spike',
    below: 'drop',
}

/** `selectedDateRange` reads a bucket's end off the next bucket's start, and leaves the last one
 *  open-ended at "now". That suits the viewer's sparkline, whose newest bucket is still filling,
 *  but every bucket here is a complete interval: an open end would pull in the current, uncharted
 *  interval on top of the one the user clicked. Appending the exclusive window end closes it. */
export function clickableBucketTimes(times: string[]): string[] {
    const last = times[times.length - 1]
    const step = times.length > 1 ? Date.parse(times[1]) - Date.parse(times[0]) : 0
    if (!(step > 0)) {
        return times
    }
    return [...times, new Date(Date.parse(last) + step).toISOString()]
}

export interface AnomalyBandChartProps {
    buckets: LogsSeriesBandBucketApi[]
    onBucketClick?: (dateRange: DateRange) => void
}

export function AnomalyBandChart({ buckets, onBucketClick }: AnomalyBandChartProps): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => buildBandChartData(buckets), [buckets])

    const series = useMemo<Series[]>(
        () => [{ key: OBSERVED_KEY, label: 'Observed', data: data.observed }],
        [data.observed]
    )

    // A marker's color varies per bucket, which an area fill can't express, so the out-of-band
    // points are their own overlay rather than a second series.
    const markers = useMemo<AnomalyMarker[]>(
        () =>
            data.outOfBand.flatMap((state, index) =>
                state
                    ? [
                          {
                              dataIndex: index,
                              value: data.observed[index],
                              color: OUT_OF_BAND_POINT_COLOR[state],
                              yAxisId: DEFAULT_Y_AXIS_ID,
                          },
                      ]
                    : []
            ),
        [data.outOfBand, data.observed]
    )

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            // Bucket times are UTC, and the timestamps around this chart render in the viewer's
            // zone, so the axis reads there too. The grain has to be stated: without it the axis
            // builds no date formatter and prints raw ISO labels. The endpoint is hourly-only.
            xAxis: { timezone: dayjs.tz.guess(), interval: 'hour' },
            yAxis: { tickFormatter: humanFriendlyNumber },
            confidenceIntervals: [{ seriesKey: OBSERVED_KEY, lower: data.lower, upper: data.upper }],
        }),
        [data.lower, data.upper]
    )

    const onPointClick = useMemo(() => {
        if (!onBucketClick) {
            return undefined
        }
        const clickTimes = clickableBucketTimes(data.labels)
        return ({ dataIndex }: PointClickData) => {
            const dateRange = selectedDateRange(clickTimes, dataIndex, dataIndex)
            if (dateRange) {
                onBucketClick(dateRange)
            }
        }
    }, [data.labels, onBucketClick])

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => {
            const bucket = buckets[ctx.dataIndex]
            const outOfBand = data.outOfBand[ctx.dataIndex]
            return (
                <DefaultTooltip
                    {...ctx}
                    labelFormatter={(label) => dayjs(label).format('MMM D, HH:mm')}
                    valueFormatter={(value) =>
                        `${humanFriendlyNumber(value)}${outOfBand ? ` (${OUT_OF_BAND_LABEL[outOfBand]})` : ''}`
                    }
                    footer={bucket ? bandSummary(bucket) : null}
                />
            )
        },
        [buckets, data.outOfBand]
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
                onPointClick={onPointClick}
                dataAttr="logs-anomaly-band-chart"
            >
                <AnomalyPointsLayer markers={markers} radius={4} />
            </TimeSeriesLineChart>
        </div>
    )
}

function bandSummary(bucket: LogsSeriesBandBucketApi): string {
    if (bucket.lower == null || bucket.upper == null) {
        return 'No baseline yet'
    }
    return `Expected ${humanFriendlyNumber(bucket.lower)} to ${humanFriendlyNumber(bucket.upper)}`
}
