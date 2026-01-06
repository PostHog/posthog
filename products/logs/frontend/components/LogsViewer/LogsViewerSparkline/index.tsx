import { useCallback, useMemo } from 'react'

import { LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { shortTimeZone } from 'lib/utils'

import { DateRange, LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'

export interface LogsSparklineData {
    data: {
        color: string | undefined
        name: string
        values: number[]
    }[]
    dates: string[]
    labels: string[]
}

interface LogsViewerSparklineProps {
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
    displayTimezone: string // IANA timezone string (e.g. "UTC", "America/New_York", "Europe/London")
    breakdownBy: LogsSparklineBreakdownBy
    onBreakdownByChange: (breakdownBy: LogsSparklineBreakdownBy) => void
}

const BREAKDOWN_OPTIONS: { value: LogsSparklineBreakdownBy; label: string }[] = [
    { value: 'severity', label: 'Severity' },
    { value: 'service', label: 'Service' },
]

export function LogsSparkline({
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
    displayTimezone,
    breakdownBy,
    onBreakdownByChange,
}: LogsViewerSparklineProps): JSX.Element | null {
    const showServiceBreakdown = useFeatureFlag('LOGS_SPARKLINE_SERVICE_BREAKDOWN')

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
        return sparklineData.dates.map((date) => dayjs(date).toISOString())
    }, [sparklineData.dates])

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
            {showServiceBreakdown && (
                <div className="flex items-center justify-between">
                    <span className="text-xs text-muted">Volume over time</span>
                    <LemonSelect
                        size="xsmall"
                        value={breakdownBy}
                        onChange={(value) => value && onBreakdownByChange(value)}
                        options={BREAKDOWN_OPTIONS}
                    />
                </div>
            )}
            <div className="relative h-32">
                {sparklineData.data.length > 0 ? (
                    <Sparkline
                        labels={sparklineLabels}
                        data={sparklineData.data}
                        className="w-full h-full"
                        onSelectionChange={onSelectionChange}
                        withXScale={withXScale}
                        renderLabel={renderLabel}
                        tooltipRowCutoff={20}
                    />
                ) : !sparklineLoading ? (
                    <div className="h-full text-muted flex items-center justify-center">
                        No results matching filters
                    </div>
                ) : null}
                {sparklineLoading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
