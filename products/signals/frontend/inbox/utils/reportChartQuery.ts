import { DataVisualizationNode, InsightVizNode, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isInsightVizNode, isSavedInsightNode, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * Strip the chrome a query node carries for the insight scene (filter bar, header, results table)
 * so the report shows the chart alone. A scout writes the query against the insight schema, so it
 * can arrive with any of these turned on. Mirrors what `NotebookNodeQuery` does for the same reason.
 */
export function asEmbeddedChart(query: Record<string, any>): Node {
    const node = { ...query, full: false } as any
    if (isInsightVizNode(node) || isSavedInsightNode(node)) {
        node.showFilters = false
        node.showHeader = false
        node.showTable = false
        node.showCorrelationTable = false
        node.embedded = true
        // Forced on rather than left alone: an explicit `false` (which the notebook query node sets,
        // and a scout can copy from one) makes `InsightVizDisplay` omit the result body entirely, so
        // the report would draw a titled card with nothing in it.
        node.showResults = true
    }
    return node as Node
}

/**
 * A SQL node draws a table unless it was given a graphical display, and only a graph needs a box.
 *
 * `Auto` is not one: it defers to the data visualization, which reads the result and draws a table
 * for nonnumeric columns or a bold number for a single numeric one. Neither wants a graph's fixed
 * height — the table ends up clipped into a scrolling region and the number sits in an oversized
 * card — and nothing here can tell which it will be before the query returns. So it sizes to its
 * content, like the table an absent display already produces.
 */
export function isGraphicalSqlNode(query: Node): boolean {
    if (!isDataVisualizationNode(query)) {
        return false
    }
    const { display } = query as DataVisualizationNode
    return !!display && display !== ChartDisplayType.ActionsTable && display !== ChartDisplayType.Auto
}

// Displays that are not a graph over time: they need more room than a compact surface has.
const NON_GRAPH_DISPLAYS = new Set<string | undefined>([
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.WorldMap,
])

/**
 * The chart's query as a bare graph for a compact surface, or null when it is not a graph. Only trends
 * and SQL graphs qualify: a saved insight loads through its own scene logic, retention and paths draw a
 * grid or a fan of rows, and a table or a single number needs more room.
 */
export function reportChartGraphQuery(chart: ReportChartApi): Node | null {
    if (!chart.query || typeof chart.query !== 'object') {
        return null
    }
    const query = asEmbeddedChart(chart.query as Record<string, any>)
    if (isInsightVizNode(query)) {
        const { source } = query as InsightVizNode
        return isTrendsQuery(source) && !NON_GRAPH_DISPLAYS.has(source.trendsFilter?.display) ? query : null
    }
    return isGraphicalSqlNode(query) && !NON_GRAPH_DISPLAYS.has((query as DataVisualizationNode).display) ? query : null
}
