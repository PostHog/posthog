import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonSegmentedButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils'

import { SparklineTimezone, logsLogic } from '../logsLogic'

export function LogsSparkline(): JSX.Element {
    const { sparklineData, sparklineLoading, sparklineTimezone } = useValues(logsLogic)
    const { setDateRangeFromSparkline, setSparklineTimezone } = useActions(logsLogic)

    const isUTC = sparklineTimezone === SparklineTimezone.UTC
    const deviceTimezone = shortTimeZone()
    const showTimezoneToggle = deviceTimezone !== null && deviceTimezone !== 'UTC'

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
                        const d = isUTC ? dayjs(value).utc() : dayjs(value)
                        return d.format(tickFormat)
                    },
                },
                time: {
                    unit: timeUnit,
                },
            } as AnyScaleOptions
        },
        [timeUnit, tickFormat, isUTC]
    )

    const renderLabel = useCallback(
        (label: string): string => {
            const d = isUTC ? dayjs(label).utc() : dayjs(label)
            const tz = isUTC ? 'UTC' : shortTimeZone(undefined, d.toDate())
            return `${d.format('D MMM YYYY HH:mm:ss')} ${tz}`
        },
        [isUTC]
    )

    const sparklineLabels = useMemo(() => {
        return sparklineData.dates.map((date) => dayjs(date).toISOString())
    }, [sparklineData.dates])

    const onSelectionChange = useCallback(
        (selection: { startIndex: number; endIndex: number }): void => {
            setDateRangeFromSparkline(selection.startIndex, selection.endIndex)
        },
        [setDateRangeFromSparkline]
    )

    return (
        <div className="relative h-40 flex flex-col">
            {showTimezoneToggle && (
                <div className="absolute top-1 right-1 z-10">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={sparklineTimezone}
                        onChange={(value) => setSparklineTimezone(value)}
                        options={[
                            { value: SparklineTimezone.UTC, label: 'UTC' },
                            { value: SparklineTimezone.Device, label: deviceTimezone ?? 'Device' },
                        ]}
                    />
                </div>
            )}
            {sparklineData.data.length > 0 ? (
                <Sparkline
                    labels={sparklineLabels}
                    data={sparklineData.data}
                    className="w-full flex-1"
                    onSelectionChange={onSelectionChange}
                    withXScale={withXScale}
                    renderLabel={renderLabel}
                />
            ) : !sparklineLoading ? (
                <div className="flex-1 text-muted flex items-center justify-center">No results matching filters</div>
            ) : null}
            {sparklineLoading && <SpinnerOverlay />}
        </div>
    )
}
