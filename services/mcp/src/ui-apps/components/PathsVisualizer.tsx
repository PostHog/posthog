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

// The busiest transitions carry the story; past this many the ribbons are too thin to read and
// the layout's iterative relaxation stops being cheap inside an embedded app.
const MAX_EDGES = 60

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

function parseUrl(value: string): URL | null {
    try {
        return new URL(value)
    } catch {
        return null
    }
}

/** Page URLs read as their path in the compact chart. The host stays when the result spans more
 *  than one origin, and a hash stays when it looks like a route, so two steps that differ only
 *  there keep distinct labels. Anything that is not a URL (an event name) stays as is. */
function nodeLabel(value: string, singleOrigin: boolean): string {
    const url = parseUrl(value)
    if (!url) {
        return value
    }
    const route = url.hash.includes('/') ? url.hash : ''
    const path = `${url.pathname}${url.search}${route}`
    return singleOrigin ? path || value : `${url.host}${path}`
}

interface PathsGraph {
    /** Node `meta` is the full value from the result key, for the tooltip. */
    nodes: SankeyNodeInput<string>[]
    links: SankeyLinkInput<PathsResultItem>[]
    columnLabels: string[]
}

/** One node per `<step>_<value>` key, so a page seen at two steps is two nodes that share a label
 *  and therefore a color. Each node is pinned to its step's column, so a path that ends early or
 *  an edge whose earlier steps were cut from the result still sit under the right header. */
function buildPathsGraph(edges: PathsResult): PathsGraph {
    const keys = new Set(edges.flatMap((edge) => [edge.source, edge.target]))
    const origins = new Set<string>()
    for (const key of keys) {
        const url = parseUrl(parseNode(key).path)
        if (url) {
            origins.add(url.origin)
        }
    }
    const singleOrigin = origins.size <= 1

    const nodes: SankeyNodeInput<string>[] = []
    let maxStep = 0
    for (const key of keys) {
        const { step, path } = parseNode(key)
        maxStep = Math.max(maxStep, step)
        nodes.push({ id: key, label: nodeLabel(path, singleOrigin), meta: path, column: Math.max(0, step - 1) })
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
    return { nodes, links, columnLabels }
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
    const graph = useMemo(() => buildPathsGraph(edges), [edges])
    const config = useMemo<SankeyChartConfig>(
        () => ({ ...CHART_CONFIG, columnLabels: graph.columnLabels }),
        [graph.columnLabels]
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

    // Users who start a path: the outflow of the nodes nothing leads into.
    const hasIncoming = new Set(edges.map((edge) => edge.target))
    const totalUsers = edges
        .filter((edge) => !hasIncoming.has(edge.source))
        .reduce((sum, edge) => sum + (edge.value ?? 0), 0)
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
                        {labelOf.get(edge.source)} to {labelOf.get(edge.target)}: {formatNumber(edge.value ?? 0)} users
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
                across <strong className="text-foreground">{graph.columnLabels.length}</strong> step
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
