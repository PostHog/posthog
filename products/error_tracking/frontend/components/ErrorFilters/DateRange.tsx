import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { errorFiltersLogic } from './errorFiltersLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => !['Yesterday', 'All time'].includes(dm.key))

export const DateRangeFilter = ({
    className,
    fullWidth = false,
    size = 'small',
}: {
    className?: string
    fullWidth?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element => {
    const { dateRange } = useValues(errorFiltersLogic)
    const { setDateRange } = useActions(errorFiltersLogic)
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
