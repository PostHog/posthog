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
    p25Seconds: number | null
    p50Seconds: number | null
    meanSeconds: number | null
    p75Seconds: number | null
    maxSeconds: number | null
}

export interface MergeToDeployBoxPlotProps {
    /** One entry per bucket, oldest first. */
    buckets: BoxPlotBucket[]
    /** Value formatter for the tooltip rows (seconds in, short label out). */
    formatSeconds: (seconds: number) => string
    className?: string
}

/** Per-bucket sample counts, carried into the tooltip through the series meta. */
interface BucketMeta {
    counts: number[]
}

function toDatum(bucket: BoxPlotBucket): BoxPlotDatum | null {
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
    return {
        min: bucket.minSeconds,
        p25: bucket.p25Seconds,
        median: bucket.p50Seconds,
        mean: bucket.meanSeconds,
        p75: bucket.p75Seconds,
        max: bucket.maxSeconds,
    }
}

/**
 * One box-and-whisker per bucket (quill BoxPlot): whisker min→max, box p25→p75, a median line
 * and a mean dot, on a shared seconds scale. Empty buckets stay empty slots so a quiet stretch
 * reads as "nothing deployed", not missing data.
 */
export function MergeToDeployBoxPlot({ buckets, formatSeconds, className }: MergeToDeployBoxPlotProps): JSX.Element {
    const theme = useChartTheme()
    const labels = useMemo(() => buckets.map((bucket) => bucket.label), [buckets])
    const series = useMemo<BoxPlotSeries<BucketMeta>[]>(
        () => [
            {
                key: 'merge_to_deploy',
                label: 'Merge to deploy',
                data: buckets.map(toDatum),
                meta: { counts: buckets.map((bucket) => bucket.count) },
            },
        ],
        [buckets]
    )
    return (
        // The chart's root is a `flex-1` child, so the sized wrapper must be a flex column —
        // in a plain block parent the canvas measures 0px tall and paints nothing.
        <div className={cn('flex h-64 flex-col', className)}>
            <BoxPlot<BucketMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={{ yTickFormatter: formatSeconds }}
                dataAttr="merge-to-deploy-box-plot"
                tooltip={(ctx) => <BucketTooltip ctx={ctx} formatSeconds={formatSeconds} />}
            />
        </div>
    )
}

function BucketTooltip({
    ctx,
    formatSeconds,
}: {
    ctx: BoxPlotTooltipContext<BucketMeta>
    formatSeconds: (seconds: number) => string
}): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const datum = entry?.series.meta?.datums?.[ctx.dataIndex]
    if (!datum) {
        return null
    }
    const count = entry?.series.meta?.user?.counts?.[ctx.dataIndex] ?? 0
    const rows: [string, number][] = [
        ['Max', datum.max],
        ['75th percentile', datum.p75],
        ['Median', datum.median],
        ['Mean', datum.mean],
        ['25th percentile', datum.p25],
        ['Min', datum.min],
    ]
    return (
        <TooltipSurface data-attr="merge-to-deploy-box-plot-tooltip">
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
