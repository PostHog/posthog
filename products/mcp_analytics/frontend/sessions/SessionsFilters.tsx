import { useActions, useValues } from 'kea'

import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { McpDateFilter } from '../components/McpDateFilter'
import { McpSharedFilters } from '../components/McpSharedFilters'
import { DEFAULT_SESSIONS_FILTERS, mcpSessionsLogic } from './mcpSessionsLogic'

export function SessionsFilters(): JSX.Element {
    const { filters, dateFilter, sessionsLoading, toolCallsBySessionLoading } = useValues(mcpSessionsLogic)
    const { setFilters, setDateFilter, refreshSessions } = useActions(mcpSessionsLogic)

    return (
        <McpSharedFilters
            pageKey="mcp-sessions"
            dataAttrPrefix="mcp-sessions"
            onRefresh={refreshSessions}
            refreshing={sessionsLoading || toolCallsBySessionLoading}
            hasPageFilters={!!filters.search}
            onClearPageFilters={() => setFilters(DEFAULT_SESSIONS_FILTERS)}
        >
            <AnalyticsSearchInput
                value={filters.search}
                onChange={(search) => setFilters({ search })}
                label="Search sessions"
                placeholder="Search sessions"
                dataAttr="mcp-sessions-filter-search"
                className="max-w-64 min-w-32 flex-[1_1_8rem]"
            />
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={setDateFilter}
                dataAttr="mcp-sessions-date-filter"
            />
        </McpSharedFilters>
    )
}
