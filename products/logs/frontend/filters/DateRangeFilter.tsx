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
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date: dayjs.Dayjs): string => {
            return date.subtract(30, 'minute').format(DATE_TIME_FORMAT)
        },
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hours',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 4 hours',
        values: ['-4h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(4, 'h'), date.endOf('d')),
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
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
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
