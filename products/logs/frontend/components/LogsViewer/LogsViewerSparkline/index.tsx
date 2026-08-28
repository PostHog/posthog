import { useCallback, useMemo } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'
import { DefaultTooltip, HighlightedRange, TimeSeriesBarChart } from '@posthog/quill-charts'
import type { DateRangeZoomData, Series, TimeSeriesBarChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { shortTimeZone } from 'lib/utils/timezones'

import { DateRange } from '~/queries/schema/schema-general'

import type { VisibleLogsTimeRange } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'

import { highlightedBucketRange, selectedDateRange } from './bucketRanges'

export interface LogsSparklineData {
    data: {
        color: string | undefined
        name: string
        values: number[]
    }[]
    dates: string[]
}

export interface LogsViewerSparklineProps {
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
    displayTimezone: string // IANA timezone string (e.g. "UTC", "America/New_York", "Europe/London")
    collapsed?: boolean
    onToggleCollapse?: () => void
    incompleteBarIndices?: number[]
    visibleRowDateRange?: VisibleLogsTimeRange | null
}

export function LogsSparkline({
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
    displayTimezone,
    collapsed = false,
    onToggleCollapse,
    incompleteBarIndices,
    visibleRowDateRange,
}: LogsViewerSparklineProps): JSX.Element | null {
    const theme = useChartTheme()

    // Quill's automatic date axis has no seconds mode, and buckets target ~50 across the queried
    // range, so an hour of logs lands under a minute per bucket and needs explicit formats.
    const tickFormat = useMemo(() => {
        if (!sparklineData.dates.length) {
            return 'HH:mm:ss'
        }
        const hoursDiff = dayjs(sparklineData.dates[sparklineData.dates.length - 1]).diff(
            dayjs(sparklineData.dates[0]),
            'hours'
        )
        if (hoursDiff <= 6) {
            return 'HH:mm:ss'
        }
        return hoursDiff <= 48 ? 'HH:mm' : 'D MMM HH:mm'
    }, [sparklineData.dates])

    const sparklineLabels = useMemo(
        () => sparklineData.dates.map((date) => dayjs(date).toISOString()),
        [sparklineData.dates]
    )

    const series = useMemo<Series[]>(
        () =>
            sparklineData.data.map((timeseries) => ({
                key: timeseries.name,
                label: timeseries.name,
                data: timeseries.values,
                // The logic hands back vars.scss color names ('danger', 'brand-blue'); a canvas
                // fill needs a real color. `theme` is a dep so a light/dark flip re-resolves them.
                color: getColorVar(timeseries.color || 'muted'),
                // Buckets past the ingestion checkpoint are always a trailing run.
                ...(incompleteBarIndices?.length
                    ? { stroke: { partial: { fromIndex: Math.min(...incompleteBarIndices) } } }
                    : {}),
            })),
        [sparklineData.data, incompleteBarIndices, theme]
    )

    const highlight = useMemo(() => {
        if (!visibleRowDateRange || !sparklineLabels.length) {
            return null
        }
        return highlightedBucketRange(
            sparklineLabels.map((label) => dayjs(label).valueOf()),
            dayjs(visibleRowDateRange.date_from).valueOf(),
            dayjs(visibleRowDateRange.date_to).valueOf()
        )
    }, [visibleRowDateRange, sparklineLabels])

    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { tickFormatter: (value: string) => dayjs(value).tz(displayTimezone).format(tickFormat) },
            yAxis: { tickFormatter: humanFriendlyNumber },
            barCornerRadius: 2,
            // severity_text is free-form, so top-10 values plus the other row can overflow the
            // tooltip; pinning makes it scrollable.
            tooltip: { pinnable: true },
        }),
        [displayTimezone, tickFormat]
    )

    const tooltipHeader = useCallback(
        (label: string): string => {
            const date = dayjs(label).tz(displayTimezone)
            const tz = displayTimezone === 'UTC' ? 'UTC' : (shortTimeZone(displayTimezone, date.toDate()) ?? 'Local')
            return `${date.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [displayTimezone]
    )

    // `hideZeroRows` and `sortedByValue` are `DefaultTooltip` props that `config.tooltip` does not
    // forward, so a sparse bucket would otherwise list every zero-count series.
    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <DefaultTooltip
                {...ctx}
                hideZeroRows
                sortedByValue
                valueFormatter={(value: number) => humanFriendlyNumber(value)}
                labelFormatter={tooltipHeader}
            />
        ),
        [tooltipHeader]
    )

    // Wired straight through rather than via `useDateRangeZoom()`, because that hook's flag would
    // take this drag away from anyone the rollout has not reached, and it already ships to everyone.
    const onDateRangeZoom = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData): void => {
            const dateRange = selectedDateRange(sparklineData.dates, startIndex, endIndex)
            if (dateRange) {
                onDateRangeChange(dateRange)
            }
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
                    onClick={onToggleCollapse}
                    aria-expanded={!collapsed}
                    aria-controls="logs-sparkline-content"
                >
                    <span className="text-xs text-muted">Volume over time</span>
                </LemonButton>
            </div>
            {!collapsed && (
                // Quill chart roots are `flex-1`, so the sized box has to be a flex column.
                <div id="logs-sparkline-content" className="relative h-32 flex flex-col">
                    {series.length > 0 ? (
                        <TimeSeriesBarChart
                            series={series}
                            labels={sparklineLabels}
                            theme={theme}
                            config={config}
                            onDateRangeZoom={onDateRangeZoom}
                            tooltip={renderTooltip}
                            dataAttr="logs-viewer-volume-chart"
                        >
                            {highlight ? (
                                <HighlightedRange start={highlight.startIndex} end={highlight.endIndex} />
                            ) : null}
                        </TimeSeriesBarChart>
                    ) : !sparklineLoading ? (
                        <div className="h-full text-muted flex items-center justify-center">
                            No results matching filters
                        </div>
                    ) : null}
                    {sparklineLoading && <SpinnerOverlay />}
                </div>
            )}
        </div>
    )
}
