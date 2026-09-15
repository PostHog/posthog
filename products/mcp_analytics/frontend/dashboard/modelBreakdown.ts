import { dayjs } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { DateRange, HogQLFilters, MCPModelBreakdownItem, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
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
        breakdownFilter: {
            breakdown: "coalesce(nullIf(trim(toString(properties.$mcp_llm_model)), ''), 'Unknown')",
            breakdown_type: 'hogql',
            breakdown_limit: 50,
        },
        trendsFilter: { display: ChartDisplayType.ActionsTable },
    }
}

export function freezeModelDateRange(dateRange: DateRange | undefined, timezone: string): DateRange {
    if (dateRange?.date_to) {
        return dateRange
    }
    const dateFrom = dateRange?.date_from ?? '-7d'
    const components = dateStringToComponents(dateFrom)
    let start = components ? dateStringToDayJs(dateFrom, timezone) : null
    // Match the model query's relative hour rounding before sending an explicit range.
    if (start && components?.unit === 'hour') {
        start = start.startOf('hour')
    }
    return {
        ...dateRange,
        date_from: start?.toISOString() ?? dateFrom,
        date_to: dayjs().toISOString(),
        explicitDate: true,
    }
}
