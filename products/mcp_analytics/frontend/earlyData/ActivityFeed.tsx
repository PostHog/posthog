import { useActions, useValues } from 'kea'
import { MouseEvent, useCallback, useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableNode } from '~/queries/schema/schema-general'

import { ToolCallFeed } from '../components/ToolCallFeed'
import { MCP_ACTIVITY_DATA_COLLECTION_ID, MCP_ACTIVITY_UNIQUE_KEY } from '../components/toolCallFeedQuery'
import { ActivityDrawer } from './ActivityDrawer'
import { activityDrawerLogic, toActivityDrawerRow } from './activityDrawerLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

const OPEN_ROW_CLASS = 'LemonTable__row--status-highlighted'

// Skip clicks on links or buttons, and modified clicks.
function opensDrawer(event: MouseEvent): boolean {
    const hasOwnHandler = event.target instanceof Element && !!event.target.closest('button, a, [role="button"]')
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && !hasOwnHandler
}

// Rendered after the table, so the table builds the data node with its full props first.
function ActivityDrawerRowsSync({ query }: { query: DataTableNode['source'] }): null {
    const { response } = useValues(dataNodeLogic({ key: MCP_ACTIVITY_UNIQUE_KEY, query }))
    const { setRows } = useActions(activityDrawerLogic)

    useEffect(() => {
        const results = response && 'results' in response && Array.isArray(response.results) ? response.results : []
        setRows(results.flatMap((result) => toActivityDrawerRow(result) ?? []))
    }, [response, setRows])

    return null
}

export function ActivityFeed(): JSX.Element {
    const { activityQuery } = useValues(mcpEarlyDataLogic)
    const { setActivityQuery } = useActions(mcpEarlyDataLogic)
    const { openedRow } = useValues(activityDrawerLogic)
    const { openRow } = useActions(activityDrawerLogic)
    const openEventId = openedRow?.eventId

    const rowProps = useCallback(
        (record: unknown) => {
            const row = toActivityDrawerRow((record as DataTableRow | null)?.result)
            if (!row) {
                return {}
            }
            return {
                className: cn('cursor-pointer', row.eventId === openEventId && OPEN_ROW_CLASS),
                onClick: (event: MouseEvent) => {
                    if (opensDrawer(event)) {
                        openRow(row, 'list')
                    }
                },
            }
        },
        [openEventId, openRow]
    )

    return (
        <section className="flex flex-col" data-attr="mcp-analytics-activity-feed">
            {/* Day dividers sit flush left. */}
            <div className="flex [&_.DataTable\_\_row--category\_row]:text-left">
                <ToolCallFeed
                    query={activityQuery}
                    setQuery={setActivityQuery}
                    uniqueKey={MCP_ACTIVITY_UNIQUE_KEY}
                    dataNodeCollectionId={MCP_ACTIVITY_DATA_COLLECTION_ID}
                    attachTo={mcpEarlyDataLogic}
                    rowProps={rowProps}
                />
            </div>
            <ActivityDrawerRowsSync query={activityQuery.source} />
            <ActivityDrawer />
        </section>
    )
}
