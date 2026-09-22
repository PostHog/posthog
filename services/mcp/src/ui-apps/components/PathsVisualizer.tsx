import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { SankeyChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { SankeyChartConfig, SankeyLinkInput, SankeyNodeInput, SankeyTooltipContext } from '@posthog/quill-charts'

import { ChartHeader } from './ChartHeader'
import { useMcpChartTheme } from './charts/theme'
import type { PathsResult, PathsResultItem, PathsVisualizerProps } from './types'
import { formatDuration, formatNumber } from './utils'

const TITLE = 'Paths'

const CHART_CONFIG: SankeyChartConfig = {
    nodePadding: 6,
    linkOpacity: 0.35,
    showNodeValues: true,
    valueFormatter: formatNumber,
}

/** Node keys are `<stepIndex>_<value>`; split into the step number and the path/value. */
function parseNode(key: string): { step: number; path: string } {
    const sep = key.indexOf('_')
    if (sep === -1) {
        return { step: 0, path: key }
    }
    const step = Number.parseInt(key.slice(0, sep), 10)
    return { step: Number.isNaN(step) ? 0 : step, path: key.slice(sep + 1) }
}

/** Page URLs read as their path in the compact chart; anything else (an event name) stays as is. */
function nodeLabel(path: string): string {
    try {
        const url = new URL(path)
        return `${url.pathname}${url.search}` || path
    } catch {
        return path
    }
}

interface PathsGraph {
    nodes: SankeyNodeInput[]
    links: SankeyLinkInput<PathsResultItem>[]
    columnLabels: string[]
}

/** One node per `<step>_<value>` key, so a page seen at two steps is two nodes that share a label
 *  and therefore a color. Each node is pinned to its step's column, so a path that ends early or
 *  an edge whose earlier steps were cut from the result still sit under the right header. */
function buildPathsGraph(edges: PathsResult): PathsGraph {
    const nodes = new Map<string, SankeyNodeInput>()
    let maxStep = 0
    for (const edge of edges) {
        for (const key of [edge.source, edge.target]) {
            if (!nodes.has(key)) {
                const { step, path } = parseNode(key)
                maxStep = Math.max(maxStep, step)
                nodes.set(key, { id: key, label: nodeLabel(path), column: Math.max(0, step - 1) })
            }
        }
    }
    const links = edges.map(
        (edge): SankeyLinkInput<PathsResultItem> => ({
            source: edge.source,
            target: edge.target,
            value: edge.value ?? 0,
            meta: edge,
        })
    )
    const columnLabels = Array.from({ length: maxStep }, (_, i) => `Step ${i + 1}`)
    return { nodes: [...nodes.values()], links, columnLabels }
}

function PathsTooltip({ ctx }: { ctx: SankeyTooltipContext<unknown, PathsResultItem> }): ReactElement {
    const { hit } = ctx
    if (hit.kind === 'node') {
        return (
            <TooltipSurface>
                <div className="flex items-center gap-2">
                    <TooltipSwatch color={hit.node.color} />
                    <span className="font-semibold">{hit.node.label}</span>
                </div>
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
            <div>{formatNumber(link.value)} users</div>
            {link.meta?.average_conversion_time != null && (
                <div>{formatDuration(link.meta.average_conversion_time)} on average</div>
            )}
        </TooltipSurface>
    )
}

function renderTooltip(ctx: SankeyTooltipContext<unknown, PathsResultItem>): ReactElement {
    return <PathsTooltip ctx={ctx} />
}

export function PathsVisualizer({ results }: PathsVisualizerProps): ReactElement {
    const theme = useMcpChartTheme()
    const edges = useMemo(() => (Array.isArray(results) ? results : []), [results])
    const graph = useMemo(() => buildPathsGraph(edges), [edges])
    const config = useMemo<SankeyChartConfig>(
        () => ({ ...CHART_CONFIG, columnLabels: graph.columnLabels }),
        [graph.columnLabels]
    )

    if (edges.length === 0) {
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

    // Users who start a path: the outflow of the nodes nothing leads into.
    const hasIncoming = new Set(edges.map((edge) => edge.target))
    const totalUsers = edges
        .filter((edge) => !hasIncoming.has(edge.source))
        .reduce((sum, edge) => sum + (edge.value ?? 0), 0)

    return (
        <div data-attr="paths-sankey" className="w-full">
            <ChartHeader title={TITLE} />
            <div className="flex flex-col h-80 w-full">
                <SankeyChart<unknown, PathsResultItem>
                    nodes={graph.nodes}
                    links={graph.links}
                    theme={theme}
                    config={config}
                    tooltip={renderTooltip}
                />
            </div>
            <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                <strong className="text-foreground">{formatNumber(edges.length)}</strong> path transition
                {edges.length === 1 ? '' : 's'} across{' '}
                <strong className="text-foreground">{graph.columnLabels.length}</strong> step
                {graph.columnLabels.length === 1 ? '' : 's'}
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
