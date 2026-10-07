import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { SankeyChart } from '@posthog/quill-charts'
import type { SankeyChartConfig } from '@posthog/quill-charts'

import {
    buildPathsSankeyGraph,
    parsePathNodeKey,
    pathStartCount,
} from 'products/product_analytics/frontend/insights/paths/pathsChartTransforms'

import { ChartHeader } from './ChartHeader'
import { useMcpChartTheme } from './charts/theme'
import type { PathsResultItem, PathsVisualizerProps } from './types'
import { formatDuration, formatNumber } from './utils'

const TITLE = 'Paths'

// The busiest transitions carry the story; past this many the ribbons are too thin to read and
// the layout's iterative relaxation stops being cheap inside an embedded app.
const MAX_EDGES = 60

const MAX_STEPS_IN_FRAME = 5

// Bounds the scroll width, so a result with a very high step index cannot size the canvas
// to thousands of percent of the frame.
const MAX_SCROLL_COLUMNS = 25

const NODE_PADDING = 6
// Total gap one column may take out of the h-80 chart's plot, under half its height. When a dense
// column's gaps fill the plot, the layout engine draws its nodes and ribbons with no height.
const MAX_COLUMN_PADDING = 120

const CHART_CONFIG: SankeyChartConfig = {
    linkOpacity: 0.35,
    showNodeValues: true,
    valueFormatter: formatNumber,
}

/** Which steps a transition joins, so a pair of pages that repeats at two stages reads apart. */
function stepRange(edge: PathsResultItem): string {
    return `step ${parsePathNodeKey(edge.source).step} to ${parsePathNodeKey(edge.target).step}`
}

export function PathsVisualizer({ results }: PathsVisualizerProps): ReactElement {
    const theme = useMcpChartTheme()
    const allEdges = useMemo(() => (Array.isArray(results) ? results : []), [results])
    // Busiest first, so a truncated view keeps the transitions that matter.
    const edges = useMemo(
        () => [...allEdges].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, MAX_EDGES),
        [allEdges]
    )
    const graph = useMemo(() => buildPathsSankeyGraph(edges, { labelUrls: true, pinSteps: true }), [edges])
    // Step headers only line up when every node sits in its step's column.
    const columnLabels = useMemo(
        () => (graph.stepsPinned ? Array.from({ length: graph.stepCount }, (_, i) => `Step ${i + 1}`) : []),
        [graph.stepsPinned, graph.stepCount]
    )
    const nodePadding = useMemo(() => {
        const perStep = new Map<number, number>()
        for (const node of graph.nodes) {
            // Unpinned, the layout places nodes by depth, so nodes from any step can share one column.
            const step = graph.stepsPinned ? parsePathNodeKey(node.id).step : 0
            perStep.set(step, (perStep.get(step) ?? 0) + 1)
        }
        const densest = Math.max(1, ...perStep.values())
        return densest > 1 ? Math.min(NODE_PADDING, MAX_COLUMN_PADDING / (densest - 1)) : NODE_PADDING
    }, [graph.nodes, graph.stepsPinned])
    const config = useMemo<SankeyChartConfig>(
        () => ({ ...CHART_CONFIG, columnLabels, nodePadding }),
        [columnLabels, nodePadding]
    )
    const labelOf = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node.label])), [graph.nodes])

    if (allEdges.length === 0) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('generic')}</EmptyMedia>
                        <EmptyDescription>No path data available</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    const pathStarts = pathStartCount(allEdges)
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
    const truncated = edges.length < allEdges.length

    return (
        <div data-attr="paths-sankey" className="w-full">
            <ChartHeader title={TITLE} />
            <div className="h-80 w-full overflow-x-auto">
                {/* The chart sizes to its parent, so a long path needs a wider parent to scroll. */}
                <div className="flex flex-col h-full" style={{ width: chartWidth }}>
                    <SankeyChart<string, PathsResultItem>
                        nodes={graph.nodes}
                        links={graph.links}
                        theme={theme}
                        config={config}
                    />
                </div>
            </div>
            {/* The canvas has no per-ribbon semantics, so screen readers get the transitions as text. */}
            <ul className="sr-only">
                {edges.map((edge) => (
                    <li key={`${edge.source}→${edge.target}`}>
                        {labelOf.get(edge.source)} to {labelOf.get(edge.target)} ({stepRange(edge)}):{' '}
                        {formatNumber(edge.value ?? 0)} paths
                        {edge.average_conversion_time != null
                            ? `, ${formatDuration(edge.average_conversion_time)} on average`
                            : ''}
                    </li>
                ))}
            </ul>
            <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                {truncated ? (
                    <>
                        Showing the <strong className="text-foreground">{formatNumber(edges.length)}</strong> busiest of{' '}
                        <strong className="text-foreground">{formatNumber(allEdges.length)}</strong> path transitions
                    </>
                ) : (
                    <>
                        <strong className="text-foreground">{formatNumber(edges.length)}</strong> path transition
                        {edges.length === 1 ? '' : 's'}
                    </>
                )}{' '}
                across <strong className="text-foreground">{formatNumber(stepCount)}</strong> step
                {stepCount === 1 ? '' : 's'}
                {pathStarts > 0 && (
                    <>
                        {' '}
                        · <strong className="text-foreground">{formatNumber(pathStarts)}</strong> path
                        {pathStarts === 1 ? ' begins' : 's begin'} at step 1
                    </>
                )}
            </div>
        </div>
    )
}
