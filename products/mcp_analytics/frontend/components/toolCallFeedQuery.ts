import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { hogql } from 'lib/utils/hogql'

import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'
import { DataTableNode, HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { LAB_ORDER, labSqlExpression } from '../aiLabs'
import { labMark } from '../aiLabs'
import { HARNESS_BY_LABEL, harnessMark } from '../dashboard/harnessRegistry'

export const MCP_ACTIVITY_DATA_COLLECTION_ID = pageCollectionId('mcp-analytics-activity')
export const MCP_ACTIVITY_PAGE_SIZE = 100
export const MCP_ACTIVITY_MAX_ROWS = 1000
export const MCP_ACTIVITY_INTENT_COLUMN = 'properties.$mcp_intent -- Agent intent'
export const MCP_ACTIVITY_ERROR_COLUMN = 'properties.$mcp_is_error -- Error'
export const MCP_ACTIVITY_SESSION_COLUMN = 'properties.$session_id -- Session'

const harnessLabels = [...Object.keys(HARNESS_BY_LABEL), 'Unidentified client']
const clientMarkSql = hogql`transform(properties.$virt_mcp_harness, ${harnessLabels}, ${harnessLabels.map(harnessMark)}, 'Other harnesses')`
const modelMarkSql = hogql`transform(${hogql.raw(labSqlExpression('properties.$mcp_llm_model'))}, ${LAB_ORDER}, ${LAB_ORDER.map(labMark)}, 'Unbranded model')`

export const MCP_ACTIVITY_COLUMNS = [
    '*',
    `coalesce(
        nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
        if(properties.$mcp_tool_name = 'exec' AND properties.$mcp_exec_verb = 'call',
           nullIf(nullIf(toString(properties.$mcp_exec_target_tool), ''), 'unrecognized'), NULL),
        toString(properties.$mcp_tool_name)
    ) -- Tool`,
    MCP_ACTIVITY_INTENT_COLUMN,
    MCP_ACTIVITY_ERROR_COLUMN,
    'properties.$mcp_duration_ms -- Duration (ms)',
    hogql`withIcon(coalesce(nullIf(toString(properties.$mcp_client_name), ''), properties.$virt_mcp_harness), ${hogql.raw(clientMarkSql)}) -- Client`,
    hogql`withIcon(properties.$mcp_llm_model, ${hogql.raw(modelMarkSql)}) -- Model`,
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

export function withSharedFilters(
    query: DataTableNode,
    filters: Required<Pick<HogQLFilters, 'filterTestAccounts' | 'properties'>>
): DataTableNode {
    return query.source.kind === NodeKind.EventsQuery ? { ...query, source: { ...query.source, ...filters } } : query
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
