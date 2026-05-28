import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils'

import { DateMappingOption } from '~/types'

import { MetricAggregation, metricsViewerLogic } from './metricsViewerLogic'

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Count' },
    { value: 'p95', label: 'p95' },
]

// Mirrors the curated set used by `LogsViewer/Filters/DateRangeFilter`.
const DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

export interface MetricsViewerProps {
    id: string
}

export const MetricsViewer = ({ id }: MetricsViewerProps): JSX.Element => {
    const logic = metricsViewerLogic({ tabId: id })
    const {
        metricName,
        aggregation,
        dateFrom,
        dateTo,
        sparklineValues,
        sparklineLabels,
        queryResultsLoading,
        hasMetricName,
    } = useValues(logic)
    const { setMetricName, setAggregation, setDateFrom, setDateTo, fetchQueryResults } = useActions(logic)

    // Refetch whenever any filter changes — the loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [metricName, aggregation, dateFrom, dateTo]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col gap-3 flex-1 min-h-0">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    size="small"
                    placeholder="Metric name (e.g. http.server.duration)"
                    value={metricName}
                    onChange={setMetricName}
                    className="min-w-[300px]"
                />
                <LemonSelect
                    size="small"
                    value={aggregation}
                    options={AGGREGATION_OPTIONS}
                    onChange={(value) => setAggregation(value as MetricAggregation)}
                />
                <DateFilter
                    size="small"
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    dateOptions={DATE_OPTIONS}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setDateFrom(changedDateFrom)
                        setDateTo(changedDateTo)
                    }}
                    allowTimePrecision
                    allowFixedRangeWithTime
                    allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
                    use24HourFormat
                />
            </div>
            <div className="flex-1 min-h-[300px] border rounded p-3">
                {hasMetricName ? (
                    <Sparkline
                        type="line"
                        data={[{ name: aggregation, values: sparklineValues, color: 'data-color-1' }]}
                        labels={sparklineLabels}
                        loading={queryResultsLoading}
                        className="h-full"
                    />
                ) : (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        Enter a metric name to see its time series.
                    </div>
                )}
            </div>
        </div>
    )
}
