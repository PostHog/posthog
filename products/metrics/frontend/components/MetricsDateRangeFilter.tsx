import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { CUSTOM_OPTION_KEY } from 'lib/utils/dateFilters'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'

import { DateMappingOption } from '~/types'

import { metricsViewerLogic } from './metricsViewerLogic'

// Mirrors the curated set used by `LogsViewer/Filters/DateRangeFilter`.
const METRICS_DATE_OPTIONS: DateMappingOption[] = [
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

export function MetricsDateRangeFilter({ disabledReason }: { disabledReason: string | null }): JSX.Element {
    const { dateFrom, dateTo } = useValues(metricsViewerLogic)
    const { setDateFrom, setDateTo } = useActions(metricsViewerLogic)
    return (
        <DateFilter
            size="small"
            dateFrom={dateFrom}
            dateTo={dateTo}
            dateOptions={METRICS_DATE_OPTIONS}
            onChange={(changedDateFrom, changedDateTo) => {
                setDateFrom(changedDateFrom)
                setDateTo(changedDateTo)
            }}
            allowTimePrecision
            allowFixedRangeWithTime
            allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
            use24HourFormat
            disabledReason={disabledReason}
        />
    )
}
