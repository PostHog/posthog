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

// The chart draws transitions up to this step only, which bounds the scroll width and keeps every node pinned.
export const MAX_DRAWN_STEPS = 25

const NODE_PADDING = 6
// Total gap one column may take out of the h-80 chart's plot, under half its height. When a dense
// column's gaps fill the plot, the layout engine draws its nodes and ribbons with no height.
const MAX_COLUMN_PADDING = 120

export interface PathsView {
    allEdges: PathsResultItem[]
    /** The transitions the chart draws, busiest first. */
    edges: PathsResultItem[]
    truncated: boolean
    /** True when the result has transitions past `MAX_DRAWN_STEPS` that the chart leaves out. */
    stepsClipped: boolean
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
    const drawable = allEdges.filter((edge) => parsePathNodeKey(edge.target).step <= MAX_DRAWN_STEPS)
    // Busiest first, so a truncated view keeps the transitions that matter.
    const edges = [...drawable].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, MAX_EDGES)
    const graph = buildPathsSankeyGraph(edges, { labelUrls: true, pinStepsUpTo: MAX_DRAWN_STEPS })
    const columnLabels = Array.from({ length: graph.stepCount }, (_, i) => `Step ${i + 1}`)

    const perStep = new Map<number, number>()
    for (const node of graph.nodes) {
        const step = parsePathNodeKey(node.id).step
        perStep.set(step, (perStep.get(step) ?? 0) + 1)
    }
    const densest = Math.max(1, ...perStep.values())
    const nodePadding = densest > 1 ? Math.min(NODE_PADDING, MAX_COLUMN_PADDING / (densest - 1)) : NODE_PADDING

    // The busiest edges can leave out the last steps, so count steps on the full result.
    const stepCount = allEdges.reduce((max, edge) => Math.max(max, parsePathNodeKey(edge.target).step), 0)
    // Past five steps the chart grows a fifth of the frame per step and scrolls, as the paths
    // insight does, so long paths keep readable columns.
    const chartWidth =
        graph.stepCount > MAX_STEPS_IN_FRAME ? `${(graph.stepCount / MAX_STEPS_IN_FRAME) * 100}%` : '100%'

    return {
        allEdges,
        edges,
        truncated: edges.length < allEdges.length,
        stepsClipped: drawable.length < allEdges.length,
        graph,
        columnLabels,
        nodePadding,
        stepCount,
        pathStarts: pathStartCount(allEdges),
        chartWidth,
    }
}
