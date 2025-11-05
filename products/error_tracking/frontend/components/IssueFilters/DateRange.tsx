import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { DATE_FORMAT, dateMapping } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { issueFiltersLogic } from './issueFiltersLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => !['Yesterday', 'All time', 'Today'].includes(dm.key))

errorTrackingDateOptions.unshift({
    key: 'Last hour',
    values: ['-1h'],
    getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(1, 'h').format(DATE_FORMAT),
})

export const DateRangeFilter = ({
    className,
    fullWidth = false,
    size = 'small',
}: {
    className?: string
    fullWidth?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element => {
    const { dateRange } = useValues(issueFiltersLogic)
    const { setDateRange } = useActions(issueFiltersLogic)
    return (
        <span className={cn('rounded bg-surface-primary', className)}>
            <DateFilter
                size={size}
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                fullWidth={fullWidth}
                dateOptions={errorTrackingDateOptions}
                onChange={(changedDateFrom, changedDateTo) =>
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }
                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            />
        </span>
    )
}
