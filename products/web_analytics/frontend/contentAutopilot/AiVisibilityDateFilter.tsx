import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import {
    AI_VISIBILITY_DATE_OPTIONS,
    type AiVisibilityFilterTab,
    DEFAULT_AI_VISIBILITY_DATE_FROM,
} from './aiVisibilityFilters'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

export const AiVisibilityDateFilter = ({ tab }: { tab: AiVisibilityFilterTab }): JSX.Element => {
    const { dateFrom, dateTo } = useValues(contentAutopilotFiltersLogic)
    const { pickDates } = useActions(contentAutopilotFiltersLogic)

    return (
        <DateFilter
            size="small"
            dateFrom={dateFrom}
            dateTo={dateTo}
            dateOptions={AI_VISIBILITY_DATE_OPTIONS}
            onChange={(nextFrom, nextTo) => pickDates(nextFrom ?? DEFAULT_AI_VISIBILITY_DATE_FROM, nextTo, tab)}
        />
    )
}
