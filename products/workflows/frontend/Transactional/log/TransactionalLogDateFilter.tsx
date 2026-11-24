import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { INVOCATIONS_DATE_OPTIONS } from 'scenes/hog-functions/invocations/invocationsDateOptions'

import { DEFAULT_LOG_FILTERS, LOG_RETENTION_DAYS } from './transactionalEmailLogLogic'

interface LogDates {
    dateFrom: string
    dateTo: string | null
}

export function TransactionalLogDateFilter({
    dateFrom,
    dateTo,
    onChange,
}: LogDates & { onChange: (dates: LogDates) => void }): JSX.Element {
    return (
        <DateFilter
            size="small"
            dateFrom={dateFrom}
            dateTo={dateTo ?? undefined}
            onChange={(from, to) => onChange({ dateFrom: from || DEFAULT_LOG_FILTERS.dateFrom, dateTo: to || null })}
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
