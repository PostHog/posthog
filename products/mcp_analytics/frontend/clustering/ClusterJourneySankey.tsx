import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import sankey, { sankeyLeft, sankeyLinkHorizontal } from '~/vendor/d3/sankey'

import type { MCPIntentClusterJourneyApi, MCPIntentClusterJourneyPathApi } from '../generated/api.schemas'

const WIDTH = 720
const HEIGHT = 300
const COLUMN_LABELS = ['Init', '1st tool', '2nd tool', '3rd tool', '4th tool', 'Outcome']
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
    outcome: 'completed' | 'error'
}

function describePath(path: MCPIntentClusterJourneyPathApi): string {
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

function buildGraph(paths: readonly MCPIntentClusterJourneyPathApi[]): {
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
                    outcome: path.outcome === 'error' ? 'error' : 'completed',
                })
            }
        }
    }

    return { nodes, links: Array.from(linkMap.values()) }
}

interface Props {
    journey: MCPIntentClusterJourneyApi | null | undefined
}

export function ClusterJourneySankey({ journey }: Props): JSX.Element | null {
    const graph = useMemo(() => (journey ? buildGraph(journey.paths) : { nodes: [], links: [] }), [journey])

    const layout = useMemo(() => {
        if (graph.nodes.length === 0 || graph.links.length === 0) {
            return null
        }
        // d3-sankey mutates the inputs, so deep-copy before passing.
        const layoutFn = sankey<JourneyNode, JourneyLink>()
            .nodeWidth(18)
            .nodePadding(10)
            .nodeAlign(sankeyLeft)
            .extent([
                [4, 14],
                [WIDTH - 4, HEIGHT - 14],
            ])
        return layoutFn({
            nodes: graph.nodes.map((n) => ({ ...n })),
            links: graph.links.map((l) => ({ ...l })),
        })
    }, [graph])

    if (!journey || !layout) {
        return (
            <div className="bg-surface-secondary rounded p-4 text-xs text-muted">
                Not enough session data yet to plot a journey. Recompute after more sessions are summarised.
            </div>
        )
    }

    const linkGen = sankeyLinkHorizontal<JourneyNode, JourneyLink>()

    return (
        <div className="flex flex-col gap-2">
            <div className="text-xs text-muted">
                {journey.total_sessions} session{journey.total_sessions === 1 ? '' : 's'} · top {journey.paths.length}{' '}
                path{journey.paths.length === 1 ? '' : 's'}
            </div>
            <div className="overflow-x-auto">
                <svg width={WIDTH} height={HEIGHT} className="block">
                    <g>
                        {COLUMN_LABELS.map((label, idx) => {
                            const colWidth = (WIDTH - 8) / COLUMN_LABELS.length
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
                            const pct =
                                journey.total_sessions > 0
                                    ? Math.round((link.value / journey.total_sessions) * 1000) / 10
                                    : 0
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
            {journey.leak ? (
                <div className="text-xs text-muted leading-relaxed">
                    <span className="text-danger font-medium">Biggest leak:</span>{' '}
                    <span>
                        {describePath(journey.leak)} drains{' '}
                        <span className="font-medium">
                            {journey.leak.count} session{journey.leak.count === 1 ? '' : 's'}
                        </span>{' '}
                        into {journey.leak.outcome === 'error' ? 'Error' : 'Other'}.
                    </span>
                </div>
            ) : (
                <div className="text-xs text-muted">No failing paths in this cluster.</div>
            )}
        </div>
    )
}
