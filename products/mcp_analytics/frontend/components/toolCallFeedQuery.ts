import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { hogql } from 'lib/utils/hogql'

import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'
import { DataTableNode, HogQLFilters, NodeKind } from '~/queries/schema/schema-general'

import { LAB_ORDER, labSqlExpression } from '../aiLabs'
import { labMark } from '../aiLabs'
import { HARNESS_BY_LABEL, harnessMark } from '../dashboard/harnessRegistry'
import type { DateFilter } from '../mcpAnalyticsToolQualityLogic'

export const MCP_ACTIVITY_DATA_COLLECTION_ID = pageCollectionId('mcp-analytics-activity')
export const MCP_ACTIVITY_UNIQUE_KEY = 'mcp-analytics-activity'
export const MCP_ACTIVITY_PAGE_SIZE = 100
export const MCP_ACTIVITY_MAX_ROWS = 1000
export const MCP_ACTIVITY_INTENT_COLUMN = 'properties.$mcp_intent -- Agent intent'
// SDK versions stamp $mcp_is_error as a boolean, the string 'true', or 1; the backend treats all three as failures.
export const MCP_IS_ERROR_EXPR = "has(['true', '1'], toString(properties.$mcp_is_error))"
// The error type for a failed call ('error' when it has none), and empty for a successful one.
export const MCP_ACTIVITY_ERROR_COLUMN = `if(${MCP_IS_ERROR_EXPR}, coalesce(nullIf(toString(properties.$mcp_error_type), ''), 'error'), '') -- Error`
export const MCP_ACTIVITY_SESSION_COLUMN = 'properties.$session_id -- Session'
export const MCP_ACTIVITY_DURATION_COLUMN = 'properties.$mcp_duration_ms -- Duration (ms)'

const harnessLabels = [...Object.keys(HARNESS_BY_LABEL), 'Unidentified client']
const clientMarkSql = hogql`transform(properties.$virt_mcp_harness, ${harnessLabels}, ${harnessLabels.map(harnessMark)}, 'Other harnesses')`
const modelMarkSql = hogql`transform(${hogql.raw(labSqlExpression('properties.$mcp_llm_model'))}, ${LAB_ORDER}, ${LAB_ORDER.map(labMark)}, 'Unbranded model')`

/** The tool a call ran, resolving `exec` calls to the tool they wrapped. */
export const MCP_TOOL_EXPR = `coalesce(
        nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
        if(properties.$mcp_tool_name = 'exec' AND properties.$mcp_exec_verb = 'call',
           nullIf(nullIf(toString(properties.$mcp_exec_target_tool), ''), 'unrecognized'), NULL),
        toString(properties.$mcp_tool_name)
    )`
/** The client's self-reported name, or its harness label when it sent none. */
export const MCP_CLIENT_EXPR = `coalesce(nullIf(toString(properties.$mcp_client_name), ''), properties.$virt_mcp_harness)`
export const MCP_HARNESS_EXPR = 'toString(properties.$virt_mcp_harness)'
export const MCP_MODEL_EXPR = 'toString(properties.$mcp_llm_model)'

export const MCP_ACTIVITY_MODEL_COLUMN = hogql`withIcon(properties.$mcp_llm_model, ${hogql.raw(modelMarkSql)}) -- Model`

export const MCP_ACTIVITY_COLUMNS = [
    '*',
    `${MCP_TOOL_EXPR} -- Tool`,
    MCP_ACTIVITY_INTENT_COLUMN,
    MCP_ACTIVITY_ERROR_COLUMN,
    MCP_ACTIVITY_DURATION_COLUMN,
    hogql`withIcon(${hogql.raw(MCP_HARNESS_EXPR)}, ${hogql.raw(clientMarkSql)}) -- Harness`,
    MCP_ACTIVITY_MODEL_COLUMN,
    MCP_ACTIVITY_SESSION_COLUMN,
    'timestamp',
]

export const ACTIVITY_DEFAULT_DATE_FROM = '-7d'

export const DEFAULT_MCP_ACTIVITY_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        // The drawer opens each call's session, so the feed needs no session column.
        select: MCP_ACTIVITY_COLUMNS.filter((column) => column !== MCP_ACTIVITY_SESSION_COLUMN),
        events: [MCP_TOOL_CALL_EVENT],
        after: ACTIVITY_DEFAULT_DATE_FROM,
        orderBy: ['timestamp DESC'],
        limit: MCP_ACTIVITY_PAGE_SIZE,
    },
    embedded: false,
    expandable: false,
    showActions: true,
    // No toolbar, so no count or timings.
    showCount: false,
    showElapsedTime: false,
    showTimings: false,
    // The page's filter bar and Refresh replace these.
    showDateRange: false,
    showPropertyFilter: false,
    showReload: false,
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

export function activityDateFilter(query: DataTableNode): DateFilter {
    return query.source.kind === NodeKind.EventsQuery
        ? { dateFrom: query.source.after ?? null, dateTo: query.source.before ?? null }
        : { dateFrom: null, dateTo: null }
}

export function withSharedFilters(
    query: DataTableNode,
    filters: Required<Pick<HogQLFilters, 'filterTestAccounts' | 'properties'>>
): DataTableNode {
    return query.source.kind === NodeKind.EventsQuery ? { ...query, source: { ...query.source, ...filters } } : query
}

export function withActivityWhere(query: DataTableNode, where: string[]): DataTableNode {
    return query.source.kind === NodeKind.EventsQuery
        ? { ...query, source: { ...query.source, where: where.length > 0 ? where : undefined } }
        : query
}
