import { HogQLFilters, MCPModelBreakdownItem, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

export function summarizeModelBreakdown(rows: MCPModelBreakdownItem[]): {
    totalCalls: number
    unknownCalls: number
    identifiedShare: number
    rankedModels: MCPModelBreakdownItem[]
} {
    const totalCalls = rows.reduce((total, row) => total + row.total_calls, 0)
    const unknownCalls = rows
        .filter((row) => row.model === 'Unknown')
        .reduce((total, row) => total + row.total_calls, 0)

    return {
        totalCalls,
        unknownCalls,
        identifiedShare: totalCalls > 0 ? ((totalCalls - unknownCalls) / totalCalls) * 100 : 0,
        rankedModels: rows
            .filter((row) => row.model !== 'Unknown')
            .sort((a, b) => Number(a.model === 'Other') - Number(b.model === 'Other') || b.total_calls - a.total_calls),
    }
}

export function buildModelExplorationQuery(filters: HogQLFilters): TrendsQuery {
    return {
        ...filters,
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$mcp_tool_call', math: BaseMathType.TotalCount }],
        breakdownFilter: { breakdown: '$mcp_llm_model', breakdown_type: 'event', breakdown_limit: 50 },
        trendsFilter: { display: ChartDisplayType.ActionsTable },
    }
}
