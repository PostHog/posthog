import { useCallback, useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'
import { Heatmap, type HeatmapBrushData, useChartTheme } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils/timezones'

import type { TracingLatencyHeatmapData } from './durationBuckets'

const MAX_X_TICKS = 6

interface TracingLatencyHeatmapProps {
    data: TracingLatencyHeatmapData
    loading: boolean
    displayTimezone: string
    /** Enables the 2D brush: drag a rectangle to select a time window + duration range. */
    onBrush?: (selection: HeatmapBrushData) => void
}

export function TracingLatencyHeatmap({
    data,
    loading,
    displayTimezone,
    onBrush,
}: TracingLatencyHeatmapProps): JSX.Element {
    const theme = useChartTheme()

    // Same tick density logic as TracingSparkline: pick a format for the window size and thin
    // the categorical axis down to ~6 labels.
    const tickFormat = useMemo(() => {
        if (!data.timeBuckets.length) {
            return 'HH:mm:ss'
        }
        const hoursDiff = dayjs(data.timeBuckets[data.timeBuckets.length - 1]).diff(dayjs(data.timeBuckets[0]), 'hours')
        if (hoursDiff <= 6) {
            return 'HH:mm:ss'
        } else if (hoursDiff <= 48) {
            return 'HH:mm'
        }
        return 'D MMM HH:mm'
    }, [data.timeBuckets])

    const tickStep = Math.max(1, Math.ceil(data.timeBuckets.length / MAX_X_TICKS))
    const xTickFormatter = useCallback(
        (label: string, index: number): string | null => {
            if (index % tickStep !== 0) {
                return null
            }
            const d = displayTimezone ? dayjs(label).tz(displayTimezone) : dayjs(label)
            return d.format(tickFormat)
        },
        [tickStep, tickFormat, displayTimezone]
    )

    const tooltipLabelFormatter = useCallback(
        (label: string): string => {
            const d = displayTimezone ? dayjs(label).tz(displayTimezone) : dayjs(label)
            const tz = displayTimezone === 'UTC' ? 'UTC' : (shortTimeZone(displayTimezone, d.toDate()) ?? 'Local')
            return `${d.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [displayTimezone]
    )

    const config = useMemo(
        () => ({ xTickFormatter, tooltip: { labelFormatter: tooltipLabelFormatter } }),
        [xTickFormatter, tooltipLabelFormatter]
    )

    return (
        <div className="relative h-full w-full">
            {data.cells.length > 0 ? (
                <Heatmap
                    xLabels={data.timeBuckets}
                    yLabels={data.labels}
                    cells={data.cells}
                    theme={theme}
                    config={config}
                    onBrush={onBrush}
                    dataAttr="tracing-latency-heatmap"
                />
            ) : !loading ? (
                <div className="h-full text-muted flex items-center justify-center">No results matching filters</div>
            ) : null}
            {loading && <SpinnerOverlay />}
        </div>
    )
}
