import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { INVOCATIONS_DATE_OPTIONS } from 'scenes/hog-functions/invocations/invocationsDateOptions'

import { DEFAULT_LOG_FILTERS, LOG_RETENTION_DAYS, transactionalEmailLogLogic } from './transactionalEmailLogLogic'

export function TransactionalEmailLogDateFilter(): JSX.Element {
    const { filters } = useValues(transactionalEmailLogLogic)
    const { setFilters } = useActions(transactionalEmailLogLogic)

    return (
        <DateFilter
            size="small"
            dateFrom={filters.dateFrom}
            dateTo={filters.dateTo ?? undefined}
            onChange={(dateFrom, dateTo) =>
                setFilters({ dateFrom: dateFrom || DEFAULT_LOG_FILTERS.dateFrom, dateTo: dateTo || null })
            }
            dateOptions={INVOCATIONS_DATE_OPTIONS}
            allowTimePrecision
            allowFixedRangeWithTime
            allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
            max={LOG_RETENTION_DAYS}
            use24HourFormat
            data-attr="transactional-email-log-date-filter"
        />
    )
}
