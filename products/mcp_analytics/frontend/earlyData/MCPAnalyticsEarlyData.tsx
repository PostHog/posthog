import { useActions, useValues } from 'kea'

import { McpSharedFilters } from '../components/McpSharedFilters'
import { ActivityCards } from './ActivityCards'
import { ActivityFeed } from './ActivityFeed'
import { ActivityFilters } from './ActivityFilters'
import { activityFiltersLogic } from './activityFiltersLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

/** The Activity tab: live feed and next-step cards; default landing for low-volume projects. */
export function MCPAnalyticsActivityDashboard(): JSX.Element {
    const { overviewLoading } = useValues(mcpEarlyDataLogic)
    const { refreshAll } = useActions(mcpEarlyDataLogic)
    const { search } = useValues(activityFiltersLogic)
    const { setSearch } = useActions(activityFiltersLogic)

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-activity">
            <ActivityCards />
            <McpSharedFilters
                pageKey="mcp-activity"
                dataAttrPrefix="mcp-activity"
                onRefresh={refreshAll}
                refreshing={overviewLoading}
                hasPageFilters={!!search}
                onClearPageFilters={() => setSearch('')}
            >
                <ActivityFilters />
            </McpSharedFilters>
            <ActivityFeed />
        </div>
    )
}
