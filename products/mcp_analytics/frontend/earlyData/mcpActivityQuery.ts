import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'

import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'

import type { MCPSharedQueryFilters } from '../mcpAnalyticsFiltersLogic'

export const MCP_ACTIVITY_DATA_COLLECTION_ID = 'mcp-analytics-activity'
export const MCP_ACTIVITY_PAGE_SIZE = 100
export const MCP_ACTIVITY_MAX_ROWS = 1000
export const MCP_ACTIVITY_INTENT_COLUMN = 'properties.$mcp_intent -- Agent intent'

export const MCP_ACTIVITY_COLUMNS = [
    '*',
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) -- Tool",
    MCP_ACTIVITY_INTENT_COLUMN,
    'properties.$mcp_is_error -- Error',
    'properties.$mcp_duration_ms -- Duration (ms)',
    'properties.$mcp_client_name -- Client',
    'timestamp',
]

const DEFAULT_MCP_ACTIVITY_SOURCE: EventsQuery = {
    kind: NodeKind.EventsQuery,
    select: MCP_ACTIVITY_COLUMNS,
    events: [MCP_TOOL_CALL_EVENT],
    after: '-30d',
    orderBy: ['timestamp DESC'],
    limit: MCP_ACTIVITY_PAGE_SIZE,
}

// The property filter and test-account switch live in the tab header, shared with every other MCP
// analytics tab, so the table doesn't offer its own. Its date range stays here: that one is per tab.
export const DEFAULT_MCP_ACTIVITY_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: DEFAULT_MCP_ACTIVITY_SOURCE,
    embedded: false,
    expandable: true,
    showActions: true,
    showCount: true,
    showDateRange: true,
    showReload: true,
}

/** The feed's query: the user's own column edits when they have made any, always carrying the shared filters. */
export function buildActivityQuery(override: DataTableNode | null, filters: MCPSharedQueryFilters): DataTableNode {
    const query = override ?? DEFAULT_MCP_ACTIVITY_QUERY
    if (query.source.kind !== NodeKind.EventsQuery) {
        return query
    }
    return { ...query, source: { ...query.source, ...filters } }
}
