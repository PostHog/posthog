import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'

import { DataTableNode, HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export const MCP_ACTIVITY_DATA_COLLECTION_ID = 'mcp-analytics-activity'
export const MCP_ACTIVITY_PAGE_SIZE = 100
export const MCP_ACTIVITY_MAX_ROWS = 1000
export const MCP_ACTIVITY_INTENT_COLUMN = 'properties.$mcp_intent -- Agent intent'
export const MCP_ACTIVITY_ERROR_COLUMN = 'properties.$mcp_is_error -- Error'
export const MCP_ACTIVITY_SESSION_COLUMN = 'properties.$session_id -- Session'

export const MCP_ACTIVITY_COLUMNS = [
    '*',
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) -- Tool",
    MCP_ACTIVITY_INTENT_COLUMN,
    MCP_ACTIVITY_ERROR_COLUMN,
    'properties.$mcp_duration_ms -- Duration (ms)',
    'properties.$mcp_client_name -- Client',
    'properties.$mcp_llm_model -- Model',
    MCP_ACTIVITY_SESSION_COLUMN,
    'timestamp',
]

export const DEFAULT_MCP_ACTIVITY_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: MCP_ACTIVITY_COLUMNS,
        events: [MCP_TOOL_CALL_EVENT],
        after: '-30d',
        orderBy: ['timestamp DESC'],
        limit: MCP_ACTIVITY_PAGE_SIZE,
    },
    embedded: false,
    expandable: true,
    showActions: true,
    showCount: true,
    showDateRange: true,
    showPropertyFilter: [TaxonomicFilterGroupType.MCPProperties, TaxonomicFilterGroupType.EventProperties],
    showReload: true,
}

/** How many rows the dashboard's recent-calls card shows: a glance, not a feed. */
export const MCP_RECENT_TOOL_CALLS_LIMIT = 20

/** The same columns as the activity feed, scoped to the dashboard's filters and stripped of the toolbar. */
export function buildRecentToolCallsQuery(filters: HogQLFilters): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: MCP_ACTIVITY_COLUMNS,
            events: [MCP_TOOL_CALL_EVENT],
            after: filters.dateRange?.date_from ?? undefined,
            before: filters.dateRange?.date_to ?? undefined,
            properties: filters.properties,
            filterTestAccounts: filters.filterTestAccounts,
            orderBy: ['timestamp DESC'],
            limit: MCP_RECENT_TOOL_CALLS_LIMIT,
        },
        embedded: false,
        expandable: true,
        showActions: false,
        showCount: false,
        showDateRange: false,
        showPropertyFilter: false,
        showReload: false,
    }
}

// Matches both encodings the backend counts as failures (see MCP_ERROR_VALUES in ToolCallFeed).
const FAILED_CALLS_FILTER: AnyPropertyFilter = {
    key: '$mcp_is_error',
    value: ['true', '1'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

/** The feed narrowed to failed calls, keeping any other filter the user already applied. */
export function withFailedCallsOnly(query: DataTableNode): DataTableNode {
    if (query.source.kind !== NodeKind.EventsQuery) {
        return query
    }
    const otherFilters = (query.source.properties ?? []).filter(
        (filter) =>
            !(filter.type === FAILED_CALLS_FILTER.type && 'key' in filter && filter.key === FAILED_CALLS_FILTER.key)
    )
    return { ...query, source: { ...query.source, properties: [...otherFilters, FAILED_CALLS_FILTER] } }
}
