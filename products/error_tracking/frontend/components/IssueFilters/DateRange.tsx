import { useActions, useValues } from 'kea'

import { dateMapping } from 'lib/utils/dateFilters'

import { DateRange } from '~/queries/schema/schema-general'

import { DateRangeButton } from '../DateRangeButton'
import { issueFiltersLogic } from './issueFiltersLogic'

const ERROR_TRACKING_NAMED_CHIPS = ['Last week', 'Last month', 'This week', 'This month', 'This year']
const ERROR_TRACKING_DATE_OPTIONS = dateMapping.filter(
    (option) => !['Yesterday', 'All time', 'Today'].includes(option.key)
)

const ERROR_TRACKING_DATE_RANGE_TICKS = [
    { date_from: '-1h', label: '1 hour' },
    { date_from: '-24h', label: '24 hours' },
    { date_from: '-7d', label: '7 days' },
    { date_from: '-14d', label: '14 days' },
    { date_from: '-30d', label: '30 days' },
    { date_from: '-90d', label: '90 days' },
    { date_from: '-180d', label: '180 days' },
]

export function getNextErrorTrackingDateRange(dateRange: DateRange): { dateRange: DateRange; label: string } | null {
    const currentIndex = ERROR_TRACKING_DATE_RANGE_TICKS.findIndex(
        ({ date_from }) => dateRange.date_from === date_from && dateRange.date_to == null
    )
    if (currentIndex < 0 || currentIndex === ERROR_TRACKING_DATE_RANGE_TICKS.length - 1) {
        return null
    }

    const nextTick = ERROR_TRACKING_DATE_RANGE_TICKS[currentIndex + 1]
    return {
        dateRange: { date_from: nextTick.date_from, date_to: null },
        label: nextTick.label,
    }
}

export const DateRangeFilter = ({
    className,
    fullWidth = false,
}: {
    className?: string
    fullWidth?: boolean
}): JSX.Element => {
    const { dateRange } = useValues(issueFiltersLogic)
    const { setDateRange } = useActions(issueFiltersLogic)

    return (
        <DateRangeButton
            dateRange={dateRange}
            onChange={setDateRange}
            dateOptions={ERROR_TRACKING_DATE_OPTIONS}
            namedChips={ERROR_TRACKING_NAMED_CHIPS}
            className={className}
            fullWidth={fullWidth}
        />
    )
}
