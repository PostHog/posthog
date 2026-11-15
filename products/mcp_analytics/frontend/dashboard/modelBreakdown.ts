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

import { foldedModelLabel, isFoldedModelsLabel, modelRowLabelsByCalls, otherModelsLabel } from '../aiLabs'

function foldModelRows(rows: MCPModelBreakdownItem[], rowLabels: ReadonlyMap<string, string>): MCPModelBreakdownItem[] {
    const totals = new Map<string, number>()
    for (const row of rows) {
        const label = rowLabels.get(row.model) ?? foldedModelLabel(row.model)
        totals.set(label, (totals.get(label) ?? 0) + row.total_calls)
    }
    const rank = (model: string): number =>
        model === otherModelsLabel('Other') ? 2 : isFoldedModelsLabel(model) ? 1 : 0
    return [...totals.entries()]
        .map(([model, total_calls]) => ({ model, total_calls }))
        .sort(
            (a, b) => rank(a.model) - rank(b.model) || b.total_calls - a.total_calls || a.model.localeCompare(b.model)
        )
}

/** Pass `rowLabels` when another chart on the page shows models, so both charts put a model in the same row. */
export function summarizeModelBreakdown(
    rows: MCPModelBreakdownItem[],
    rowLabels?: ReadonlyMap<string, string>
): {
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
        rankedModels: foldModelRows(
            rows.filter((row) => row.model !== 'Unknown'),
            rowLabels?.size ? rowLabels : modelRowLabelsByCalls(rows.map((row) => [row.model, row.total_calls]))
        ),
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

const ABSOLUTE_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d/

export function freezeModelDateRange(dateRange: DateRange | undefined, timezone: string): DateRange {
    if (dateRange?.date_to) {
        // An end with a time of day stops there in the leaderboard's own query, but the model query
        // extends it to the end of that day unless explicitDate is set. Date-only and relative ends
        // snap to the end of the day in both, so they stay as they are.
        return ABSOLUTE_DATETIME.test(dateRange.date_to) ? { ...dateRange, explicitDate: true } : dateRange
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
