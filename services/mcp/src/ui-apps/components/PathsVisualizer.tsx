import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { SankeyChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { SankeyChartConfig, SankeyTooltipContext } from '@posthog/quill-charts'

import {
    buildPathsSankeyGraph,
    parsePathNodeKey,
    pathStartUsers,
} from 'products/product_analytics/frontend/insights/paths/pathsChartTransforms'

import { ChartHeader } from './ChartHeader'
import { useMcpChartTheme } from './charts/theme'
import type { PathsResultItem, PathsVisualizerProps } from './types'
import { formatDuration, formatNumber } from './utils'

const TITLE = 'Paths'

// The busiest transitions carry the story; past this many the ribbons are too thin to read and
// the layout's iterative relaxation stops being cheap inside an embedded app.
const MAX_EDGES = 60

const CHART_CONFIG: SankeyChartConfig = {
    nodePadding: 6,
    linkOpacity: 0.35,
    showNodeValues: true,
    valueFormatter: formatNumber,
}

/** Which steps a transition joins, so a pair of pages that repeats at two stages reads apart. */
function stepRange(edge: PathsResultItem): string {
    return `step ${parsePathNodeKey(edge.source).step} to ${parsePathNodeKey(edge.target).step}`
}

function PathsTooltip({ ctx }: { ctx: SankeyTooltipContext<string, PathsResultItem> }): ReactElement {
    const { hit } = ctx
    if (hit.kind === 'node') {
        return (
            <TooltipSurface>
                <div className="flex items-center gap-2">
                    <TooltipSwatch color={hit.node.color} />
                    <span className="font-semibold">{hit.node.label}</span>
                </div>
                {hit.node.meta && hit.node.meta !== hit.node.label && (
                    <div className="text-muted-foreground break-all">{hit.node.meta}</div>
                )}
                <div>{formatNumber(hit.node.value)} users</div>
            </TooltipSurface>
        )
    }
    const { link } = hit
    return (
        <TooltipSurface>
            <div className="font-semibold">
                {link.source.label} → {link.target.label}
            </div>
            {link.meta && <div className="text-muted-foreground">{stepRange(link.meta)}</div>}
            <div>{formatNumber(link.value)} users</div>
            {link.meta?.average_conversion_time != null && (
                <div>{formatDuration(link.meta.average_conversion_time)} on average</div>
            )}
        </TooltipSurface>
    )
}

function renderTooltip(ctx: SankeyTooltipContext<string, PathsResultItem>): ReactElement {
    return <PathsTooltip ctx={ctx} />
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
    const columnLabels = useMemo(
        () => Array.from({ length: graph.stepCount }, (_, i) => `Step ${i + 1}`),
        [graph.stepCount]
    )
    const config = useMemo<SankeyChartConfig>(() => ({ ...CHART_CONFIG, columnLabels }), [columnLabels])
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

    const totalUsers = pathStartUsers(allEdges)
    const truncated = edges.length < allEdges.length

    return (
        <div data-attr="paths-sankey" className="w-full">
            <ChartHeader title={TITLE} />
            <div className="flex flex-col h-80 w-full">
                <SankeyChart<string, PathsResultItem>
                    nodes={graph.nodes}
                    links={graph.links}
                    theme={theme}
                    config={config}
                    tooltip={renderTooltip}
                />
            </div>
            {/* The canvas has no per-ribbon semantics, so screen readers get the transitions as text. */}
            <ul className="sr-only">
                {edges.map((edge) => (
                    <li key={`${edge.source}→${edge.target}`}>
                        {labelOf.get(edge.source)} to {labelOf.get(edge.target)} ({stepRange(edge)}):{' '}
                        {formatNumber(edge.value ?? 0)} users
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
                across <strong className="text-foreground">{columnLabels.length}</strong> step
                {columnLabels.length === 1 ? '' : 's'}
                {totalUsers > 0 && (
                    <>
                        {' '}
                        · <strong className="text-foreground">{formatNumber(totalUsers)}</strong> users start a path
                    </>
                )}
            </div>
        </div>
    )
}
