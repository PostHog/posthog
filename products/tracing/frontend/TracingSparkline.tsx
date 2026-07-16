import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, SpinnerOverlay } from '@posthog/lemon-ui'
import type { HeatmapBrushData } from '@posthog/quill-charts'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { shortTimeZone } from 'lib/utils/timezones'

import { DateRange } from '~/queries/schema/schema-general'

import {
    type TracingDurationHistogramData,
    type TracingLatencyHeatmapData,
    type VisibleDurationRange,
    snapDurationToBucket,
} from './durationBuckets'
import { SparklineCompareOverlay } from './SparklineCompareOverlay'
import type { TracingSparklineData, VisibleSpanTimeRange } from './tracingDataLogic'
import type { TracingChartType } from './tracingFiltersLogic'
import { TracingLatencyHeatmap } from './TracingLatencyHeatmap'

interface CompareConfig {
    fullStartMs: number
    fullEndMs: number
    currentWindow: { startMs: number; endMs: number }
    previousWindow: { startMs: number; endMs: number }
    onChange: (current: { startMs: number; endMs: number }, previous: { startMs: number; endMs: number }) => void
}

interface TracingSparklineProps {
    sparklineData: TracingSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
    displayTimezone: string
    compare?: CompareConfig
    visibleRowDateRange?: VisibleSpanTimeRange | null
    /** When set, render a duration histogram instead of the time series (list sorted by duration). */
    durationHistogram?: TracingDurationHistogramData | null
    visibleRowDurationRange?: VisibleDurationRange | null
    /** Which chart fills the slot. Omitted (or 'activity') keeps today's behavior; the chart-type
     *  toggle only renders when `onChartTypeChange` is provided. */
    chartType?: TracingChartType
    onChartTypeChange?: (chartType: TracingChartType) => void
    /** When set, render the latency heatmap instead of the sparkline/histogram. The caller passes
     *  it only when the heatmap should actually show (chartType 'heatmap' and no comparison). */
    latencyHeatmap?: TracingLatencyHeatmapData | null
    latencyHeatmapLoading?: boolean
    /** Enables the heatmap's 2D brush (time window + duration range selection). */
    onHeatmapBrush?: (selection: HeatmapBrushData) => void
    /** Disables the heatmap option with an explanation (e.g. while a comparison is active). */
    heatmapDisabledReason?: string | null
}

export function TracingSparkline({
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
    displayTimezone,
    compare,
    visibleRowDateRange,
    durationHistogram,
    visibleRowDurationRange,
    chartType = 'activity',
    onChartTypeChange,
    latencyHeatmap,
    latencyHeatmapLoading = false,
    onHeatmapBrush,
    heatmapDisabledReason,
}: TracingSparklineProps): JSX.Element | null {
    const [collapsed, setCollapsed] = useState(false)
    const heatmapMode = latencyHeatmap != null
    const durationMode = !heatmapMode && durationHistogram != null

    const { timeUnit, tickFormat } = useMemo(() => {
        if (!sparklineData.dates.length) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm:ss' }
        }
        const firstDate = dayjs(sparklineData.dates[0])
        const lastDate = dayjs(sparklineData.dates[sparklineData.dates.length - 1])
        const hoursDiff = lastDate.diff(firstDate, 'hours')

        if (hoursDiff <= 1) {
            return { timeUnit: 'second' as const, tickFormat: 'HH:mm:ss' }
        } else if (hoursDiff <= 6) {
            return { timeUnit: 'minute' as const, tickFormat: 'HH:mm:ss' }
        } else if (hoursDiff <= 48) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        return { timeUnit: 'day' as const, tickFormat: 'D MMM HH:mm' }
    }, [sparklineData.dates])

    const withXScale = useCallback(
        (scale: AnyScaleOptions): AnyScaleOptions => {
            if (durationMode) {
                // Duration buckets are categorical (1ms, 2ms, 5ms, ...) — the 1-2-5 series is
                // already log-spaced, so a plain category axis renders it evenly.
                return {
                    ...scale,
                    type: 'category',
                    ticks: {
                        display: true,
                        maxRotation: 0,
                        maxTicksLimit: 8,
                        font: {
                            size: 10,
                            lineHeight: 1,
                        },
                    },
                } as AnyScaleOptions
            }
            return {
                ...scale,
                type: 'timeseries',
                ticks: {
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 6,
                    font: {
                        size: 10,
                        lineHeight: 1,
                    },
                    callback: function (value: string | number) {
                        const d = displayTimezone ? dayjs(value).tz(displayTimezone) : dayjs(value)
                        return d.format(tickFormat)
                    },
                },
                time: {
                    unit: timeUnit,
                },
            } as AnyScaleOptions
        },
        [durationMode, timeUnit, tickFormat, displayTimezone]
    )

    const renderLabel = useCallback(
        (label: string): string => {
            if (durationMode) {
                return label // bucket labels ("2ms") are already human-readable
            }
            const d = displayTimezone ? dayjs(label).tz(displayTimezone) : dayjs(label)
            const tz = displayTimezone === 'UTC' ? 'UTC' : (shortTimeZone(displayTimezone, d.toDate()) ?? 'Local')
            return `${d.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [durationMode, displayTimezone]
    )

    const sparklineLabels = useMemo(() => {
        if (durationHistogram) {
            return durationHistogram.labels
        }
        return sparklineData.dates.map((date: string) => dayjs(date).toISOString())
    }, [durationHistogram, sparklineData.dates])

    // Map the visible rows' duration range onto histogram bucket indices: snap each edge onto
    // the same 1-2-5 series the backend bucketed with, then find those buckets on the axis.
    const durationHighlightedRange = useMemo(() => {
        if (!durationHistogram || !visibleRowDurationRange || durationHistogram.bucketsNs.length === 0) {
            return null
        }
        const { bucketsNs, labels } = durationHistogram
        // An edge missing from the axis can only mean it's outside the rendered range (the axis
        // spans the data's min..max bucket), so clamp it to the nearest end.
        const startIndexRaw = bucketsNs.indexOf(snapDurationToBucket(visibleRowDurationRange.minNs))
        const endIndexRaw = bucketsNs.indexOf(snapDurationToBucket(visibleRowDurationRange.maxNs))
        const startIndex = startIndexRaw === -1 ? 0 : startIndexRaw
        const endIndex = endIndexRaw === -1 ? bucketsNs.length - 1 : endIndexRaw
        if (startIndex > endIndex) {
            return null
        }
        return { xMin: labels[startIndex], xMax: labels[endIndex + 1] ?? labels[endIndex] }
    }, [visibleRowDurationRange, durationHistogram])

    // Map the visible-row date range onto bucket indices in `dates`. Buckets are anchored at
    // their start time; the date_to edge belongs to the bucket whose start is the last one
    // <= date_to. Suppressed in compare mode, where the list (and its window) isn't shown.
    const highlightedRange = useMemo(() => {
        if (compare || !visibleRowDateRange || sparklineData.dates.length === 0) {
            return null
        }
        const fromMs = dayjs(visibleRowDateRange.date_from).valueOf()
        const toMs = dayjs(visibleRowDateRange.date_to).valueOf()
        let startIndex = -1
        let endIndex = -1
        for (let i = 0; i < sparklineData.dates.length; i++) {
            const bucketMs = dayjs(sparklineData.dates[i]).valueOf()
            if (bucketMs <= fromMs) {
                startIndex = i
            }
            if (bucketMs <= toMs) {
                endIndex = i
            } else {
                break
            }
        }
        if (startIndex === -1) {
            startIndex = 0
        }
        if (endIndex === -1 || endIndex < startIndex) {
            return null
        }
        return { xMin: sparklineLabels[startIndex], xMax: sparklineLabels[endIndex + 1] ?? sparklineLabels[endIndex] }
    }, [compare, visibleRowDateRange, sparklineData.dates, sparklineLabels])

    const onSelectionChange = useCallback(
        (selection: { startIndex: number; endIndex: number }): void => {
            const dates = sparklineData.dates
            const dateFrom = dates[selection.startIndex]
            const dateTo = dates[selection.endIndex + 1]

            if (!dateFrom) {
                return
            }

            onDateRangeChange({
                date_from: dateFrom,
                date_to: dateTo,
            })
        },
        [sparklineData.dates, onDateRangeChange]
    )

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed(!collapsed)}
                    aria-expanded={!collapsed}
                    aria-controls="tracing-sparkline-content"
                >
                    <span className="text-xs text-muted">
                        {heatmapMode ? 'Latency heatmap' : durationMode ? 'Duration distribution' : 'Volume over time'}
                    </span>
                </LemonButton>
                {onChartTypeChange && (
                    <LemonSegmentedButton
                        size="xsmall"
                        value={chartType}
                        onChange={(value) => onChartTypeChange(value as TracingChartType)}
                        options={[
                            { value: 'activity', label: 'Activity' },
                            {
                                value: 'heatmap',
                                label: 'Heatmap',
                                disabledReason: heatmapDisabledReason ?? undefined,
                            },
                        ]}
                    />
                )}
            </div>
            {!collapsed && latencyHeatmap != null && (
                <div id="tracing-sparkline-content" className="relative h-32">
                    <TracingLatencyHeatmap
                        data={latencyHeatmap}
                        loading={latencyHeatmapLoading}
                        displayTimezone={displayTimezone}
                        onBrush={onHeatmapBrush}
                    />
                </div>
            )}
            {!collapsed && !heatmapMode && (
                <div id="tracing-sparkline-content" className="relative h-32">
                    {(durationHistogram ? durationHistogram.data : sparklineData.data).length > 0 ? (
                        <Sparkline
                            labels={sparklineLabels}
                            data={durationHistogram ? durationHistogram.data : sparklineData.data}
                            className="w-full h-full"
                            // Drag-select sets the date range — meaningless on a duration axis, so
                            // disabled in duration mode (a duration-range filter is a later idea).
                            onSelectionChange={compare || durationMode ? undefined : onSelectionChange}
                            withXScale={withXScale}
                            renderLabel={renderLabel}
                            tooltipRowCutoff={100}
                            hideZerosInTooltip
                            sortTooltipByCount
                            highlightedRange={durationMode ? durationHighlightedRange : highlightedRange}
                        />
                    ) : !sparklineLoading ? (
                        <div className="h-full text-muted flex items-center justify-center">
                            No results matching filters
                        </div>
                    ) : null}
                    {compare && sparklineData.data.length > 0 && (
                        <SparklineCompareOverlay
                            fullStartMs={compare.fullStartMs}
                            fullEndMs={compare.fullEndMs}
                            currentWindow={compare.currentWindow}
                            previousWindow={compare.previousWindow}
                            onChange={compare.onChange}
                        />
                    )}
                    {sparklineLoading && <SpinnerOverlay />}
                </div>
            )}
        </div>
    )
}
