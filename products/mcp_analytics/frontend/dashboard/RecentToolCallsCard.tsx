import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { HogQLFilters } from '~/queries/schema/schema-general'

import { ToolCallFeed } from '../components/ToolCallFeed'
import { MCP_RECENT_TOOL_CALLS_LIMIT, buildRecentToolCallsQuery } from '../components/toolCallFeedQuery'

// A glance at the newest calls under the dashboard's filters. Aggregates say how the server is
// doing; this says what it did a minute ago, and links to the full feed for more.
// Rendered outside the dashboard's quill sections on purpose: the events table is a LemonUI
// component, and quill's color variables recolor its rows and expanded events.
export function RecentToolCallsCard({ filters }: { filters: HogQLFilters }): JSX.Element {
    const { searchParams } = useValues(router)
    const query = useMemo(() => buildRecentToolCallsQuery(filters), [filters])
    // Keep the dashboard's date range and filters so the full feed opens on the same calls.
    const seeAllUrl = combineUrl(urls.mcpAnalyticsActivity(), searchParams).url

    return (
        <section className="flex min-w-0 flex-col gap-2" data-attr="mcp-dashboard-recent-tool-calls">
            <div className="flex items-center justify-between gap-2">
                <h2 className="mb-0 text-xl font-semibold text-primary">Recent activity</h2>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={seeAllUrl}
                    data-attr="mcp-dashboard-recent-tool-calls-see-all"
                >
                    View all tool calls
                </LemonButton>
            </div>
            <ToolCallFeed
                query={query}
                uniqueKey="mcp-dashboard-recent-tool-calls"
                maxRows={MCP_RECENT_TOOL_CALLS_LIMIT}
            />
        </section>
    )
}
