import { useActions, useValues } from 'kea'

import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { McpDateFilter } from '../components/McpDateFilter'
import { activityFiltersLogic } from './activityFiltersLogic'

export function ActivityFilters(): JSX.Element {
    const { search, dateRange } = useValues(activityFiltersLogic)
    const { setSearch, setDateRange } = useActions(activityFiltersLogic)

    return (
        <>
            <AnalyticsSearchInput
                value={search}
                onChange={setSearch}
                label="Search tool calls"
                placeholder="Search tool calls"
                dataAttr="mcp-activity-filter-search"
                className="max-w-64 min-w-32 flex-[1_1_8rem]"
            />
            <McpDateFilter
                dateFrom={dateRange.dateFrom}
                dateTo={dateRange.dateTo}
                onChange={setDateRange}
                dataAttr="mcp-activity-filter-date"
            />
        </>
    )
}
