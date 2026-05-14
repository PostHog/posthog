import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import sankey, { sankeyLeft, sankeyLinkHorizontal } from 'lib/d3/sankey'

export type JourneyOutcome = 'completed' | 'error'

export interface JourneyPath {
    readonly steps: readonly (string | null)[]
    readonly outcome: JourneyOutcome
    readonly count: number
}

export interface JourneySankeyProps {
    paths: readonly JourneyPath[]
    totalSessions: number
    leak?: JourneyPath | null
    /** Column labels for the Sankey header — must be at least 1 + max(steps.length) + 1. */
    columnLabels?: readonly string[]
    /** Empty-state message when there's nothing to plot. */
    emptyMessage?: string
    width?: number
    height?: number
    /** When false, the leak sentence under the chart is hidden. */
    showLeakSentence?: boolean
}

const DEFAULT_WIDTH = 720
const DEFAULT_HEIGHT = 300
const DEFAULT_COLUMN_LABELS = ['Init', '1st tool', '2nd tool', '3rd tool', '4th tool', 'Outcome']
const ENDED_LABEL = 'Ended'

type NodeKind = 'init' | 'tool' | 'ended' | 'completed' | 'error'

interface JourneyNode {
    name: string
    column: number
    kind: NodeKind
}

interface JourneyLink {
    source: number
    target: number
    value: number
    outcome: JourneyOutcome
}

function describePath(path: JourneyPath): string {
    const labels = path.steps.map((step) => step ?? ENDED_LABEL)
    return labels.filter((label, idx) => label !== ENDED_LABEL || idx === labels.indexOf(ENDED_LABEL)).join(' → ')
}

function nodeFill(kind: NodeKind): string {
    switch (kind) {
        case 'init':
            return 'var(--muted)'
        case 'ended':
            return 'var(--muted-3000)'
        case 'completed':
            return 'var(--success)'
        case 'error':
            return 'var(--danger)'
        case 'tool':
        default:
            return 'var(--accent)'
    }
}

function buildGraph(paths: readonly JourneyPath[]): {
    nodes: JourneyNode[]
    links: JourneyLink[]
} {
    const nodeIndex = new Map<string, number>()
    const nodes: JourneyNode[] = []

    const getNode = (column: number, name: string, kind: NodeKind): number => {
        const key = `${column}::${name}`
        const existing = nodeIndex.get(key)
        if (existing !== undefined) {
            return existing
        }
        const idx = nodes.length
        nodeIndex.set(key, idx)
        nodes.push({ name, column, kind })
        return idx
    }

    const linkMap = new Map<string, JourneyLink>()
    const initIdx = getNode(0, 'Init', 'init')

    for (const path of paths) {
        const columns: { name: string; kind: NodeKind }[] = [{ name: 'Init', kind: 'init' }]
        for (const step of path.steps) {
            if (step === null) {
                columns.push({ name: ENDED_LABEL, kind: 'ended' })
            } else {
                columns.push({ name: step, kind: 'tool' })
            }
        }
        columns.push({
            name: path.outcome === 'error' ? 'Error' : 'Completed',
            kind: path.outcome === 'error' ? 'error' : 'completed',
        })

        for (let i = 0; i < columns.length - 1; i++) {
            const sourceCol = i === 0 ? 0 : i
            const targetCol = sourceCol + 1
            const src = sourceCol === 0 ? initIdx : getNode(sourceCol, columns[i].name, columns[i].kind)
            const tgt = getNode(targetCol, columns[i + 1].name, columns[i + 1].kind)
            const linkKey = `${src}->${tgt}::${path.outcome}`
            const existing = linkMap.get(linkKey)
            if (existing) {
                existing.value += path.count
            } else {
                linkMap.set(linkKey, {
                    source: src,
                    target: tgt,
                    value: path.count,
                    outcome: path.outcome,
                })
            }
        }
    }

    return { nodes, links: Array.from(linkMap.values()) }
}

export function JourneySankey({
    paths,
    totalSessions,
    leak,
    columnLabels = DEFAULT_COLUMN_LABELS,
    emptyMessage = 'Not enough session data yet to plot a journey.',
    width = DEFAULT_WIDTH,
    height = DEFAULT_HEIGHT,
    showLeakSentence = true,
}: JourneySankeyProps): JSX.Element {
    const graph = useMemo(() => buildGraph(paths), [paths])

    const layout = useMemo(() => {
        if (graph.nodes.length === 0 || graph.links.length === 0) {
            return null
        }
        const layoutFn = sankey<JourneyNode, JourneyLink>()
            .nodeWidth(18)
            .nodePadding(10)
            .nodeAlign(sankeyLeft)
            .extent([
                [4, 14],
                [width - 4, height - 14],
            ])
        return layoutFn({
            nodes: graph.nodes.map((n) => ({ ...n })),
            links: graph.links.map((l) => ({ ...l })),
        })
    }, [graph, width, height])

    if (!layout) {
        return <div className="bg-surface-secondary rounded p-4 text-xs text-muted">{emptyMessage}</div>
    }

    const linkGen = sankeyLinkHorizontal<JourneyNode, JourneyLink>()

    return (
        <div className="flex flex-col gap-2">
            <div className="text-xs text-muted">
                {totalSessions} session{totalSessions === 1 ? '' : 's'} · top {paths.length} path
                {paths.length === 1 ? '' : 's'}
            </div>
            <div className="overflow-x-auto">
                <svg width={width} height={height} className="block">
                    <g>
                        {columnLabels.map((label, idx) => {
                            const colWidth = (width - 8) / columnLabels.length
                            const x = 4 + colWidth * idx + colWidth / 2
                            return (
                                <text
                                    key={label}
                                    x={x}
                                    y={10}
                                    textAnchor="middle"
                                    className="fill-[var(--muted)]"
                                    fontSize={9}
                                >
                                    {label}
                                </text>
                            )
                        })}
                    </g>
                    <g>
                        {layout.links.map((link, idx) => {
                            const path = linkGen(link) ?? ''
                            const stroke = link.outcome === 'error' ? 'var(--danger)' : 'var(--accent)'
                            const sourceName = (link.source as unknown as JourneyNode).name
                            const targetName = (link.target as unknown as JourneyNode).name
                            const pct = totalSessions > 0 ? Math.round((link.value / totalSessions) * 1000) / 10 : 0
                            return (
                                <Tooltip
                                    key={idx}
                                    title={
                                        <div className="flex flex-col gap-0.5">
                                            <span className="font-semibold">
                                                {sourceName} → {targetName}
                                            </span>
                                            <span>
                                                {link.value} session{link.value === 1 ? '' : 's'} ({pct}%)
                                            </span>
                                            <span className="text-muted">
                                                Outcome: {link.outcome === 'error' ? 'error' : 'completed'}
                                            </span>
                                        </div>
                                    }
                                >
                                    <path
                                        d={path}
                                        fill="none"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            stroke,
                                            strokeOpacity: 0.45,
                                            strokeWidth: Math.max(1, link.width),
                                        }}
                                    />
                                </Tooltip>
                            )
                        })}
                    </g>
                    <g>
                        {layout.nodes.map((node, idx) => (
                            <g key={idx}>
                                <rect
                                    x={node.x0}
                                    y={node.y0}
                                    width={node.x1 - node.x0}
                                    height={Math.max(1, node.y1 - node.y0)}
                                    rx={2}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fill: nodeFill(node.kind) }}
                                />
                                <text
                                    x={node.x0 + (node.x1 - node.x0) / 2}
                                    y={node.y1 + 10}
                                    textAnchor="middle"
                                    className="fill-[var(--text-primary)]"
                                    fontSize={10}
                                >
                                    <tspan>{node.name}</tspan>
                                </text>
                            </g>
                        ))}
                    </g>
                </svg>
            </div>
            {showLeakSentence ? (
                leak ? (
                    <div className="text-xs text-muted leading-relaxed">
                        <span className="text-danger font-medium">Biggest leak:</span>{' '}
                        <span>
                            {describePath(leak)} drains{' '}
                            <span className="font-medium">
                                {leak.count} session{leak.count === 1 ? '' : 's'}
                            </span>{' '}
                            into {leak.outcome === 'error' ? 'Error' : 'Other'}.
                        </span>
                    </div>
                ) : (
                    <div className="text-xs text-muted">No failing paths.</div>
                )
            ) : null}
        </div>
    )
}
