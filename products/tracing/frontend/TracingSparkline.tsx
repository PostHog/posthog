import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { DateRange } from '~/queries/schema/schema-general'

import { SparklineCompareOverlay } from './SparklineCompareOverlay'
import type { TracingSparklineData, VisibleSpanTimeRange } from './tracingDataLogic'

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
}

export function TracingSparkline({
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
    displayTimezone,
    compare,
    visibleRowDateRange,
}: TracingSparklineProps): JSX.Element | null {
    const [collapsed, setCollapsed] = useState(false)

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
        [timeUnit, tickFormat, displayTimezone]
    )

    const renderLabel = useCallback(
        (label: string): string => {
            const d = displayTimezone ? dayjs(label).tz(displayTimezone) : dayjs(label)
            const tz = displayTimezone === 'UTC' ? 'UTC' : (shortTimeZone(displayTimezone, d.toDate()) ?? 'Local')
            return `${d.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [displayTimezone]
    )

    const sparklineLabels = useMemo(() => {
        return sparklineData.dates.map((date: string) => dayjs(date).toISOString())
    }, [sparklineData.dates])

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
        return { startIndex, endIndex }
    }, [compare, visibleRowDateRange, sparklineData.dates])

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
                    <span className="text-xs text-muted">Volume over time</span>
                </LemonButton>
            </div>
            {!collapsed && (
                <div id="tracing-sparkline-content" className="relative h-32">
                    {sparklineData.data.length > 0 ? (
                        <Sparkline
                            labels={sparklineLabels}
                            data={sparklineData.data}
                            className="w-full h-full"
                            onSelectionChange={compare ? undefined : onSelectionChange}
                            withXScale={withXScale}
                            renderLabel={renderLabel}
                            tooltipRowCutoff={100}
                            hideZerosInTooltip
                            sortTooltipByCount
                            highlightedRange={highlightedRange}
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
