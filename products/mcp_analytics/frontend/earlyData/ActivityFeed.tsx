import { useActions, useValues } from 'kea'

import { ToolCallFeed } from '../components/ToolCallFeed'
import { MCP_ACTIVITY_DATA_COLLECTION_ID } from '../components/toolCallFeedQuery'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

export function ActivityFeed(): JSX.Element {
    const { activityQuery } = useValues(mcpEarlyDataLogic)
    const { setActivityQuery } = useActions(mcpEarlyDataLogic)

    return (
        <section className="flex flex-col" data-attr="mcp-analytics-activity-feed">
            <h3 className="mb-2 text-sm font-semibold">Live activity</h3>
            {/* Capped so the page ends without scrolling past a thousand rows; the rest scrolls inside. */}
            <div className="flex max-h-[36rem] overflow-hidden">
                <ToolCallFeed
                    query={activityQuery}
                    setQuery={setActivityQuery}
                    uniqueKey="mcp-analytics-activity"
                    dataNodeCollectionId={MCP_ACTIVITY_DATA_COLLECTION_ID}
                    attachTo={mcpEarlyDataLogic}
                />
            </div>
        </section>
    )
}
