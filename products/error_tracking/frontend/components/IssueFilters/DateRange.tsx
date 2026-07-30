import { useActions, useValues } from 'kea'

import { dateMapping } from 'lib/utils/dateFilters'

import { DateRangeButton } from '../DateRangeButton'
import { issueFiltersLogic } from './issueFiltersLogic'

const ERROR_TRACKING_NAMED_CHIPS = ['Last week', 'Last month', 'This week', 'This month', 'This year']
const ERROR_TRACKING_DATE_OPTIONS = dateMapping.filter(
    (option) => !['Yesterday', 'All time', 'Today'].includes(option.key)
)

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
