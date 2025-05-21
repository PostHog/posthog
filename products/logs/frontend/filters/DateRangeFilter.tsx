import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils'

import { DateMappingOption } from '~/types'

import { logsLogic } from '../logsLogic'

const dateMapping: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date: dayjs.Dayjs): string => {
            return date.subtract(5, 'minute').format(DATE_TIME_FORMAT)
        },
        defaultInterval: 'minute',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 48 hours',
        values: ['-48h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(48, 'h'), date.endOf('d')),
        inactive: true,
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'This month',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('month'), date.endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Previous month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        inactive: true,
        defaultInterval: 'day',
    },
]

export const DateRangeFilter = (): JSX.Element => {
    const { dateRange } = useValues(logsLogic)
    const { setDateRange } = useActions(logsLogic)

    return (
        <span className="rounded bg-surface-primary">
            <DateFilter
                size="small"
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                dateOptions={dateMapping}
                onChange={(changedDateFrom, changedDateTo) => {
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }}
                allowTimePrecision
                allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks', 'months']}
            />
        </span>
    )
}
