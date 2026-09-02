import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

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
