import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { logsLogic } from '../logsLogic'

export const DateRangeFilter = (): JSX.Element => {
    const { dateRange } = useValues(logsLogic)
    const { setDateRange } = useActions(logsLogic)

    return (
        <span className="rounded bg-surface-primary">
            <DateFilter
                size="small"
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                onChange={(changedDateFrom, changedDateTo) =>
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }
                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            />
        </span>
    )
}
