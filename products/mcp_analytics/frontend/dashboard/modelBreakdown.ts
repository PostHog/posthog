import { dayjs } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import {
    DateRange,
    HogQLFilters,
    InsightVizNode,
    MCPModelBreakdownItem,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { foldedModelLabel, otherModelsLabel } from '../aiLabs'

const TOP_MODEL_ROWS = 6

function foldModelRows(rows: MCPModelBreakdownItem[]): MCPModelBreakdownItem[] {
    const top = rows
        .filter((row) => row.model !== 'Other')
        .sort((a, b) => b.total_calls - a.total_calls)
        .slice(0, TOP_MODEL_ROWS)
    const topModels = new Set(top.map((row) => row.model))
    const folded = new Map<string, number>()
    for (const row of rows) {
        if (!topModels.has(row.model)) {
            const label = foldedModelLabel(row.model)
            folded.set(label, (folded.get(label) ?? 0) + row.total_calls)
        }
    }
    const isLabless = (model: string): boolean => model === otherModelsLabel('Other')
    const foldedRows = [...folded.entries()]
        .map(([model, total_calls]) => ({ model, total_calls }))
        .sort((a, b) => Number(isLabless(a.model)) - Number(isLabless(b.model)) || b.total_calls - a.total_calls)
    return [...top, ...foldedRows]
}

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
        rankedModels: foldModelRows(rows.filter((row) => row.model !== 'Unknown')),
    }
}

export function buildModelExplorationQuery(filters: HogQLFilters): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            ...filters,
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$mcp_tool_call', math: BaseMathType.TotalCount }],
            breakdownFilter: {
                breakdown: "coalesce(nullIf(trim(toString(properties.$mcp_llm_model)), ''), 'Unknown')",
                breakdown_type: 'hogql',
                breakdown_limit: 50,
            },
            trendsFilter: { display: ChartDisplayType.ActionsTable },
        },
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
