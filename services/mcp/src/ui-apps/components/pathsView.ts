import {
    buildPathsSankeyGraph,
    parsePathNodeKey,
    pathStartCount,
} from 'products/product_analytics/frontend/insights/paths/pathsChartTransforms'
import type { PathsSankeyGraph } from 'products/product_analytics/frontend/insights/paths/pathsChartTransforms'

import type { PathsResultItem } from './types'

// The busiest transitions carry the story; past this many the ribbons are too thin to read and
// the layout's iterative relaxation stops being cheap inside an embedded app.
export const MAX_EDGES = 60

const MAX_STEPS_IN_FRAME = 5

// Bounds the scroll width, so a result with a very high step index cannot size the canvas
// to thousands of percent of the frame.
export const MAX_SCROLL_COLUMNS = 25

const NODE_PADDING = 6
// Total gap one column may take out of the h-80 chart's plot, under half its height. When a dense
// column's gaps fill the plot, the layout engine draws its nodes and ribbons with no height.
const MAX_COLUMN_PADDING = 120

export interface PathsView {
    allEdges: PathsResultItem[]
    /** The transitions the chart draws, busiest first. */
    edges: PathsResultItem[]
    truncated: boolean
    graph: PathsSankeyGraph<PathsResultItem>
    columnLabels: string[]
    nodePadding: number
    /** The highest step in the full result, not only in the drawn transitions. */
    stepCount: number
    pathStarts: number
    /** CSS width of the chart's scroll content. */
    chartWidth: string
}

export function buildPathsView(results: unknown): PathsView {
    const allEdges: PathsResultItem[] = Array.isArray(results) ? results : []
    // Busiest first, so a truncated view keeps the transitions that matter.
    const edges = [...allEdges].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, MAX_EDGES)
    const graph = buildPathsSankeyGraph(edges, { labelUrls: true, pinStepsUpTo: MAX_SCROLL_COLUMNS })
    // Step headers only line up when every node sits in its step's column.
    const columnLabels = graph.stepsPinned ? Array.from({ length: graph.stepCount }, (_, i) => `Step ${i + 1}`) : []

    const perStep = new Map<number, number>()
    for (const node of graph.nodes) {
        // Unpinned, the layout places nodes by depth, so nodes from any step can share one column.
        const step = graph.stepsPinned ? parsePathNodeKey(node.id).step : 0
        perStep.set(step, (perStep.get(step) ?? 0) + 1)
    }
    const densest = Math.max(1, ...perStep.values())
    const nodePadding = densest > 1 ? Math.min(NODE_PADDING, MAX_COLUMN_PADDING / (densest - 1)) : NODE_PADDING

    // The busiest edges can leave out the last steps, so count steps on the full result.
    const stepCount = allEdges.reduce((max, edge) => Math.max(max, parsePathNodeKey(edge.target).step), 0)
    // Past five steps the chart grows a fifth of the frame per step and scrolls, as the paths
    // insight does, so long paths keep readable columns.
    // Unpinned, the chart lays nodes out by depth, and every edge moves one step on, so the
    // distinct steps bound its columns where the highest step index does not.
    const columnCount = Math.min(
        graph.stepsPinned ? graph.stepCount : new Set(graph.nodes.map((node) => parsePathNodeKey(node.id).step)).size,
        MAX_SCROLL_COLUMNS
    )
    const chartWidth = columnCount > MAX_STEPS_IN_FRAME ? `${(columnCount / MAX_STEPS_IN_FRAME) * 100}%` : '100%'

    return {
        allEdges,
        edges,
        truncated: edges.length < allEdges.length,
        graph,
        columnLabels,
        nodePadding,
        stepCount,
        pathStarts: pathStartCount(allEdges),
        chartWidth,
    }
}
