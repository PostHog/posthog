import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    BarChart,
    type BarChartConfig,
    createXAxisTickCallback,
    type DateRangeZoomData,
    DefaultTooltip,
    type HeatmapBrushData,
    HighlightedRange,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
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
    const theme = useChartTheme()
    const heatmapMode = latencyHeatmap != null
    const durationMode = !heatmapMode && durationHistogram != null

    const seriesSource = durationMode ? durationHistogram!.data : sparklineData.data
    const series = useMemo<Series[]>(
        () =>
            seriesSource.map((s) => ({
                key: s.name,
                label: s.name,
                data: s.values,
                color: getColorVar(s.color),
            })),
        [seriesSource]
    )

    // Duration mode is categorical (1ms, 2ms, ...); activity mode is a time axis keyed on ISO dates.
    const timeConfig = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: {
                tickFormatter: createXAxisTickCallback({ allDays: sparklineData.dates, timezone: displayTimezone }),
            },
        }),
        [sparklineData.dates, displayTimezone]
    )
    const durationConfig = useChartConfig<BarChartConfig>(() => ({}), [])

    const tooltipLabelFormatter = useCallback(
        (label: string): string => {
            const d = displayTimezone ? dayjs(label).tz(displayTimezone) : dayjs(label)
            const tz = displayTimezone === 'UTC' ? 'UTC' : (shortTimeZone(displayTimezone, d.toDate()) ?? 'Local')
            return `${d.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [displayTimezone]
    )

    // Map the visible rows' duration range onto histogram bucket indices: snap each edge onto
    // the same 1-2-5 series the backend bucketed with, then find those buckets on the axis.
    const durationHighlight = useMemo(() => {
        if (!durationHistogram || !visibleRowDurationRange || durationHistogram.bucketsNs.length === 0) {
            return null
        }
        const { bucketsNs, labels } = durationHistogram
        const startIndexRaw = bucketsNs.indexOf(snapDurationToBucket(visibleRowDurationRange.minNs))
        const endIndexRaw = bucketsNs.indexOf(snapDurationToBucket(visibleRowDurationRange.maxNs))
        const startIndex = startIndexRaw === -1 ? 0 : startIndexRaw
        const endIndex = endIndexRaw === -1 ? bucketsNs.length - 1 : endIndexRaw
        if (startIndex > endIndex) {
            return null
        }
        return { start: labels[startIndex], end: labels[endIndex] }
    }, [visibleRowDurationRange, durationHistogram])

    // Map the visible-row date range onto bucket indices in `dates`. Buckets are anchored at
    // their start time; the date_to edge belongs to the bucket whose start is the last one
    // <= date_to. Suppressed in compare mode, where the list (and its window) isn't shown.
    const activityHighlight = useMemo(() => {
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
        return { start: sparklineData.dates[startIndex], end: sparklineData.dates[endIndex] }
    }, [compare, visibleRowDateRange, sparklineData.dates])

    // Drag-select sets the date range — the drag is the only way to narrow the list, so it's wired
    // directly rather than through the drag-to-zoom flag. Meaningless on a duration axis.
    const onDateRangeZoom = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData): void => {
            const dateFrom = sparklineData.dates[startIndex]
            const dateTo = sparklineData.dates[endIndex + 1]
            if (dateFrom) {
                onDateRangeChange({ date_from: dateFrom, date_to: dateTo })
            }
        },
        [sparklineData.dates, onDateRangeChange]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <DefaultTooltip
                {...ctx}
                hideZeroRows
                sortedByValue
                valueFormatter={(value) => humanFriendlyNumber(value)}
                labelFormatter={durationMode ? undefined : tooltipLabelFormatter}
            />
        ),
        [durationMode, tooltipLabelFormatter]
    )

    const hasData = seriesSource.length > 0

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
                <div id="tracing-sparkline-content" className="relative h-32 flex flex-col">
                    {hasData ? (
                        durationMode ? (
                            <BarChart
                                series={series}
                                labels={durationHistogram!.labels}
                                theme={theme}
                                config={durationConfig}
                                tooltip={renderTooltip}
                            >
                                {durationHighlight && (
                                    <HighlightedRange start={durationHighlight.start} end={durationHighlight.end} />
                                )}
                            </BarChart>
                        ) : (
                            <TimeSeriesBarChart
                                series={series}
                                labels={sparklineData.dates}
                                theme={theme}
                                config={timeConfig}
                                onDateRangeZoom={compare ? undefined : onDateRangeZoom}
                                tooltip={renderTooltip}
                            >
                                {activityHighlight && (
                                    <HighlightedRange start={activityHighlight.start} end={activityHighlight.end} />
                                )}
                            </TimeSeriesBarChart>
                        )
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
