import { useMemo } from 'react'

import { DefaultTooltip, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'
import type { ChartTheme, PointClickData, Series } from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { Skeleton } from 'lib/ui/quill'
import { formatBucketLabel } from 'lib/utils/timeBuckets'

import { IntervalType } from '~/types'

import { BandFilter, ExceptionBand } from './releaseBreakdown'

const CHART_HEIGHT = 'h-[260px]'

export function ExceptionBandChart({
    bands,
    labels,
    loading,
    theme,
    timezone,
    interval,
    onSelectBand,
}: {
    bands: ExceptionBand[]
    /** Bucket keys the bands' counts are aligned to. */
    labels: string[]
    loading: boolean
    theme: ChartTheme
    timezone: string
    interval: IntervalType
    onSelectBand: (filters: BandFilter[]) => void
}): JSX.Element {
    const series = useMemo<Series<ExceptionBand>[]>(
        () =>
            bands.map((band) => ({
                key: band.key,
                label: band.label,
                color: band.color,
                data: band.counts,
                meta: band,
            })),
        [bands]
    )
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'stacked',
            barCornerRadius: 4,
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            xAxis: { interval, timezone },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, interval]
    )

    const onPointClick = ({ series: clicked }: PointClickData<ExceptionBand>): void => {
        if (clicked.meta?.filters) {
            onSelectBand(clicked.meta.filters)
        }
    }

    if (loading) {
        return <Skeleton className={`w-full ${CHART_HEIGHT}`} />
    }
    if (bands.length === 0) {
        return (
            <div className="py-6 text-center text-xs text-secondary">
                No exceptions in this period, so there is nothing to break down.
            </div>
        )
    }
    return (
        <div className={`flex flex-col ${CHART_HEIGHT}`}>
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                config={config}
                theme={theme}
                onPointClick={onPointClick}
                dataAttr="error-tracking-insights-breakdown"
                tooltip={(context) => (
                    <DefaultTooltip
                        {...context}
                        hideZeroRows
                        sortedByValue
                        showTotal
                        labelFormatter={(label) => formatBucketLabel(label, interval)}
                        valueFormatter={(value) => `${value} ${value === 1 ? 'exception' : 'exceptions'}`}
                    />
                )}
            />
        </div>
    )
}
