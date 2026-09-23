import { useMemo } from 'react'

import { BoxPlot, TooltipSurface, useChartTheme } from '@posthog/quill-charts'
import type { BoxPlotDatum, BoxPlotSeries, BoxPlotTooltipContext } from '@posthog/quill-charts'

import { cn } from 'lib/utils/css-classes'

export interface BoxPlotBucket {
    /** x-axis and tooltip label for the bucket (e.g. its date). Must be unique across buckets. */
    label: string
    /** Samples in the bucket; 0 renders an empty slot. */
    count: number
    minSeconds: number | null
    p05Seconds: number | null
    p25Seconds: number | null
    p50Seconds: number | null
    meanSeconds: number | null
    p75Seconds: number | null
    p95Seconds: number | null
    maxSeconds: number | null
}

export interface LeadTimeBoxPlotProps {
    /** Series identity: chart key and the label shown in the tooltip legend. */
    seriesKey: string
    seriesLabel: string
    /** One entry per bucket, oldest first. */
    buckets: BoxPlotBucket[]
    /** Value formatter for the tooltip rows (seconds in, short label out). */
    formatSeconds: (seconds: number) => string
    /** Draw the whiskers at p5/p95 instead of min/max, so one extreme PR can't flatten the boxes. */
    excludeOutliers?: boolean
    /** List the buckets down the side with the time axis along the bottom. Suits a few buckets. */
    horizontal?: boolean
    /** Put the time axis on a log scale, so minutes and days both stay readable on one axis. */
    logScale?: boolean
    dataAttr: string
    className?: string
}

/** Per-bucket sample counts, carried into the tooltip through the series meta. */
interface BucketMeta {
    counts: number[]
}

/** The six numbers a box draws, for the checks that have to cover all of them. */
const BOX_STATS = ['min', 'p25', 'median', 'mean', 'p75', 'max'] as const

function toDatum(bucket: BoxPlotBucket, excludeOutliers: boolean): BoxPlotDatum | null {
    if (
        bucket.count === 0 ||
        bucket.minSeconds == null ||
        bucket.p25Seconds == null ||
        bucket.p50Seconds == null ||
        bucket.meanSeconds == null ||
        bucket.p75Seconds == null ||
        bucket.maxSeconds == null
    ) {
        return null
    }
    // Older cached responses may lack p5/p95; fall back to the full range rather than dropping the bucket.
    const lower = excludeOutliers ? (bucket.p05Seconds ?? bucket.minSeconds) : bucket.minSeconds
    const upper = excludeOutliers ? (bucket.p95Seconds ?? bucket.maxSeconds) : bucket.maxSeconds
    return {
        min: lower,
        p25: bucket.p25Seconds,
        median: bucket.p50Seconds,
        mean: bucket.meanSeconds,
        p75: bucket.p75Seconds,
        max: upper,
    }
}

/**
 * One box-and-whisker per bucket (quill BoxPlot): whisker min→max, box p25→p75, a median line
 * and a mean dot, on a shared seconds scale. Empty buckets stay empty slots so a quiet stretch
 * reads as "nothing deployed", not missing data. One lead-time stage per instance; the Deploys
 * tab stacks three vertical ones so the stages compare bucket by bucket.
 */
export function LeadTimeBoxPlot({
    seriesKey,
    seriesLabel,
    buckets,
    formatSeconds,
    excludeOutliers = false,
    horizontal = false,
    logScale = false,
    dataAttr,
    className,
}: LeadTimeBoxPlotProps): JSX.Element {
    const theme = useChartTheme()
    const labels = useMemo(() => buckets.map((bucket) => bucket.label), [buckets])
    const series = useMemo<BoxPlotSeries<BucketMeta>[]>(
        () => [
            {
                key: seriesKey,
                label: seriesLabel,
                data: buckets.map((bucket) => toDatum(bucket, excludeOutliers)),
                meta: { counts: buckets.map((bucket) => bucket.count) },
            },
        ],
        [seriesKey, seriesLabel, buckets, excludeOutliers]
    )
    const hasZeroDuration = useMemo(
        () => series[0].data.some((datum) => datum != null && BOX_STATS.some((stat) => datum[stat] <= 0)),
        [series]
    )
    const config = useMemo(
        () => ({
            yTickFormatter: formatSeconds,
            axisOrientation: horizontal ? ('horizontal' as const) : ('vertical' as const),
            // A log axis has no zero: the scale clamps a zero-second stat onto the axis floor, where
            // it would read as a real duration. Such a bucket falls back to the linear axis.
            yScaleType: logScale && !hasZeroDuration ? ('log' as const) : ('linear' as const),
        }),
        [formatSeconds, horizontal, logScale, hasZeroDuration]
    )
    return (
        // The chart's root is a `flex-1` child, so the sized wrapper must be a flex column —
        // in a plain block parent the canvas measures 0px tall and paints nothing.
        <div className={cn('flex h-48 flex-col', className)}>
            <BoxPlot<BucketMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                dataAttr={dataAttr}
                tooltip={(ctx) => (
                    <BucketTooltip
                        ctx={ctx}
                        dataAttr={dataAttr}
                        formatSeconds={formatSeconds}
                        excludeOutliers={excludeOutliers}
                    />
                )}
            />
        </div>
    )
}

function BucketTooltip({
    ctx,
    dataAttr,
    formatSeconds,
    excludeOutliers,
}: {
    ctx: BoxPlotTooltipContext<BucketMeta>
    dataAttr: string
    formatSeconds: (seconds: number) => string
    excludeOutliers: boolean
}): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const datum = entry?.series.meta?.datums?.[ctx.dataIndex]
    if (!datum) {
        return null
    }
    const count = entry?.series.meta?.user?.counts?.[ctx.dataIndex] ?? 0
    const rows: [string, number][] = [
        [excludeOutliers ? '95th percentile' : 'Max', datum.max],
        ['75th percentile', datum.p75],
        ['Median', datum.median],
        ['Mean', datum.mean],
        ['25th percentile', datum.p25],
        [excludeOutliers ? '5th percentile' : 'Min', datum.min],
    ]
    return (
        <TooltipSurface data-attr={`${dataAttr}-tooltip`}>
            <div className="font-semibold">{ctx.label}</div>
            <div className="mb-1 opacity-70">
                {count} PR{count === 1 ? '' : 's'} deployed
            </div>
            <table className="border-collapse">
                <tbody>
                    {rows.map(([label, value]) => (
                        <tr key={label}>
                            <td className="pr-3 opacity-70">{label}</td>
                            <td className="font-medium">{formatSeconds(value)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </TooltipSurface>
    )
}
