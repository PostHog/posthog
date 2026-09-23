import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { HogQLFilters } from '~/queries/schema/schema-general'

import { ToolCallFeed } from '../components/ToolCallFeed'
import { MCP_RECENT_TOOL_CALLS_LIMIT, buildRecentToolCallsQuery } from '../components/toolCallFeedQuery'

// A glance at the newest calls under the dashboard's filters. Aggregates say how the server is
// doing; this says what it did a minute ago, and links to the full feed for more. The Activity
// feed keeps its own filters, so the link carries none of the dashboard's.
// Rendered outside the dashboard's quill sections on purpose: the events table is a LemonUI
// component, and quill's color variables recolor its rows and expanded events.
export function RecentToolCallsCard({ filters }: { filters: HogQLFilters }): JSX.Element {
    const query = useMemo(() => buildRecentToolCallsQuery(filters), [filters])

    return (
        <section className="flex min-w-0 flex-col gap-2" data-attr="mcp-dashboard-recent-tool-calls">
            <div className="flex items-center justify-between gap-2">
                <h2 className="mb-0 text-xl font-semibold text-primary">Recent activity</h2>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.mcpAnalyticsActivity()}
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
