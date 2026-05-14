import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    Handle,
    MarkerType,
    Node,
    Position,
    ReactFlow,
    ReactFlowProvider,
    applyNodeChanges,
    type NodeChange,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { getElk } from 'lib/elk'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { GitHogFlowEdge, GitHogFlowGraph, GitHogFlowNode } from './gitHogPullRequestDataFlowLogic'

const NODE_WIDTH = 200
const NODE_HEIGHT = 64

export type DiffStatus = 'kept' | 'added' | 'removed'

interface DataFlowNodeData extends Record<string, unknown> {
    node: GitHogFlowNode
    diff: DiffStatus
}

function nodeColors(diff: DiffStatus, kind: string): { bg: string; border: string; fg: string } {
    if (diff === 'added') {
        return { bg: 'rgba(34, 197, 94, 0.15)', border: 'rgb(34, 197, 94)', fg: 'rgb(20, 83, 45)' }
    }
    if (diff === 'removed') {
        return { bg: 'rgba(239, 68, 68, 0.15)', border: 'rgb(239, 68, 68)', fg: 'rgb(127, 29, 29)' }
    }
    if (kind === 'entry') {
        return { bg: 'rgba(59, 130, 246, 0.12)', border: 'rgb(59, 130, 246)', fg: 'rgb(30, 58, 138)' }
    }
    if (kind === 'side_effect') {
        return { bg: 'rgba(168, 85, 247, 0.12)', border: 'rgb(168, 85, 247)', fg: 'rgb(88, 28, 135)' }
    }
    if (kind === 'return') {
        return { bg: 'rgba(107, 114, 128, 0.12)', border: 'rgb(107, 114, 128)', fg: 'rgb(55, 65, 81)' }
    }
    return { bg: 'rgba(148, 163, 184, 0.12)', border: 'rgb(148, 163, 184)', fg: 'rgb(51, 65, 85)' }
}

function FlowNodeCard({ data }: { data: DataFlowNodeData }): JSX.Element {
    const { node, diff } = data
    const c = nodeColors(diff, node.kind)
    const prefix = diff === 'added' ? '+ ' : diff === 'removed' ? '− ' : ''
    return (
        <div
            className="rounded-md text-xs px-3 py-2 shadow-sm relative"
            style={{
                width: NODE_WIDTH,
                minHeight: NODE_HEIGHT,
                background: c.bg,
                border: `1.5px solid ${c.border}`,
                color: c.fg,
            }}
            title={node.detail || undefined}
        >
            <Handle
                type="target"
                position={Position.Left}
                style={{ background: c.border, border: 'none', width: 6, height: 6 }}
            />
            <div className="font-semibold leading-tight">
                {prefix}
                {node.label}
            </div>
            {node.file && <div className="font-mono opacity-70 truncate mt-0.5">{node.file}</div>}
            <Handle
                type="source"
                position={Position.Right}
                style={{ background: c.border, border: 'none', width: 6, height: 6 }}
            />
        </div>
    )
}

const NODE_TYPES = { flowNode: FlowNodeCard }

async function layoutGraph(
    graph: GitHogFlowGraph,
    diffByNodeId: Map<string, DiffStatus>,
    diffByEdgeKey: Map<string, DiffStatus>
): Promise<{ nodes: Node<DataFlowNodeData>[]; edges: Edge[] }> {
    const elk = await getElk()
    const layout = await elk.layout({
        id: 'root',
        layoutOptions: {
            'elk.algorithm': 'layered',
            'elk.direction': 'RIGHT',
            'elk.layered.spacing.nodeNodeBetweenLayers': '80',
            'elk.spacing.nodeNode': '40',
            'elk.spacing.edgeNode': '20',
            'elk.layered.nodePlacement.strategy': 'SIMPLE',
        },
        children: graph.nodes.map((n) => ({
            id: n.id,
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
        })),
        edges: graph.edges.map((e, idx) => ({
            id: `${e.source}->${e.target}#${idx}`,
            sources: [e.source],
            targets: [e.target],
        })),
    })

    const nodes: Node<DataFlowNodeData>[] = (layout.children || []).map((laid) => {
        const node = graph.nodes.find((n) => n.id === laid.id)!
        return {
            id: laid.id,
            type: 'flowNode',
            position: { x: laid.x ?? 0, y: laid.y ?? 0 },
            data: { node, diff: diffByNodeId.get(laid.id) ?? 'kept' },
            draggable: true,
            connectable: false,
        }
    })

    const edges: Edge[] = graph.edges.map((e, idx) => {
        const diff = diffByEdgeKey.get(`${e.source}->${e.target}`) ?? 'kept'
        // Brighter neutral so kept-edges stay visible in dark mode (slate-300 ~ readable on
        // both light and dark canvases; added/removed already pop on their own).
        const stroke = diff === 'added' ? 'rgb(34,197,94)' : diff === 'removed' ? 'rgb(239,68,68)' : 'rgb(203,213,225)'
        return {
            id: `${e.source}->${e.target}#${idx}`,
            source: e.source,
            target: e.target,
            label: e.label || undefined,
            labelStyle: { fill: stroke, fontWeight: 600, fontSize: 11 },
            labelShowBg: false,
            style: { stroke, strokeWidth: diff === 'added' ? 3 : 2 },
            markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 18, height: 18 },
            // No animation: marching-ants caused label flicker. Use thicker stroke for "added".
            animated: false,
        }
    })

    return { nodes, edges }
}

export interface DataFlowGraphProps {
    graph: GitHogFlowGraph
    /** Map of node id → diff status. Default = all kept. */
    nodeDiff?: Map<string, DiffStatus>
    /** Map of `${source}->${target}` → diff status. Default = all kept. */
    edgeDiff?: Map<string, DiffStatus>
    /** Tailwind height class, e.g. "h-96". */
    heightClass?: string
}

function DataFlowGraphInner({
    graph: rawGraph,
    nodeDiff,
    edgeDiff,
    heightClass = 'h-96',
}: DataFlowGraphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    // Memoize `safeGraph` so the effect dep is stable across re-renders. Without this,
    // safeGraph builds a fresh object every render → useEffect refires → setLayouted
    // → re-render → loop. That loop is what made the edge labels flicker.
    const graph = useMemo(() => safeGraph(rawGraph), [rawGraph])
    // Same identity-stability concern: parents that don't pass diff maps would otherwise
    // get a brand-new `new Map()` every render → useEffect refire loop.
    const stableNodeDiff = useMemo(() => nodeDiff ?? new Map<string, DiffStatus>(), [nodeDiff])
    const stableEdgeDiff = useMemo(() => edgeDiff ?? new Map<string, DiffStatus>(), [edgeDiff])
    const [nodes, setNodes] = useState<Node<DataFlowNodeData>[]>([])
    const [edges, setEdges] = useState<Edge[]>([])
    const [layoutReady, setLayoutReady] = useState(false)

    useEffect(() => {
        let cancelled = false
        setLayoutReady(false)
        layoutGraph(graph, stableNodeDiff, stableEdgeDiff).then((res) => {
            if (cancelled) {
                return
            }
            setNodes(res.nodes)
            setEdges(res.edges)
            setLayoutReady(true)
        })
        return () => {
            cancelled = true
        }
    }, [graph, stableNodeDiff, stableEdgeDiff])

    const onNodesChange = useCallback(
        (changes: NodeChange<Node<DataFlowNodeData>>[]) => setNodes((prev) => applyNodeChanges(changes, prev)),
        []
    )

    if (!graph.nodes.length) {
        return (
            <div
                className={`flex items-center justify-center text-secondary text-sm border border-dashed rounded ${heightClass}`}
            >
                Empty flow
            </div>
        )
    }
    if (!layoutReady) {
        return (
            <div className={`flex items-center justify-center text-secondary text-sm ${heightClass}`}>Laying out…</div>
        )
    }

    return (
        <div className={`${heightClass} border rounded overflow-hidden`}>
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                nodeTypes={NODE_TYPES}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                fitView
                proOptions={{ hideAttribution: true }}
                nodesDraggable
                nodesConnectable={false}
                elementsSelectable
            >
                <Background gap={24} variant={BackgroundVariant.Dots} />
                <Controls showInteractive={false} />
            </ReactFlow>
        </div>
    )
}

export function DataFlowGraph(props: DataFlowGraphProps): JSX.Element {
    return (
        <ReactFlowProvider>
            <DataFlowGraphInner {...props} />
        </ReactFlowProvider>
    )
}

/** Normalize a possibly-undefined graph payload to the canonical shape. */
export function safeGraph(g: GitHogFlowGraph | null | undefined): GitHogFlowGraph {
    return { nodes: g?.nodes ?? [], edges: g?.edges ?? [] }
}

/** Build diff maps from a before+after graph pair using stable node ids. */
export function computeFlowDiff(
    beforeRaw: GitHogFlowGraph | null | undefined,
    afterRaw: GitHogFlowGraph | null | undefined
): {
    unionGraph: GitHogFlowGraph
    nodeDiff: Map<string, DiffStatus>
    edgeDiff: Map<string, DiffStatus>
} {
    const before = safeGraph(beforeRaw)
    const after = safeGraph(afterRaw)
    const beforeNodeIds = new Set(before.nodes.map((n) => n.id))
    const afterNodeIds = new Set(after.nodes.map((n) => n.id))
    const nodeById = new Map<string, GitHogFlowNode>()
    after.nodes.forEach((n) => nodeById.set(n.id, n))
    // before overrides only when after doesn't have it (so we preserve removed node labels)
    before.nodes.forEach((n) => {
        if (!nodeById.has(n.id)) {
            nodeById.set(n.id, n)
        }
    })
    const unionNodes = Array.from(nodeById.values())
    const nodeDiff = new Map<string, DiffStatus>()
    unionNodes.forEach((n) => {
        if (beforeNodeIds.has(n.id) && afterNodeIds.has(n.id)) {
            nodeDiff.set(n.id, 'kept')
        } else if (afterNodeIds.has(n.id)) {
            nodeDiff.set(n.id, 'added')
        } else {
            nodeDiff.set(n.id, 'removed')
        }
    })

    const edgeKey = (e: GitHogFlowEdge): string => `${e.source}->${e.target}`
    const beforeEdgeKeys = new Set(before.edges.map(edgeKey))
    const afterEdgeKeys = new Set(after.edges.map(edgeKey))
    const edgeMap = new Map<string, GitHogFlowEdge>()
    after.edges.forEach((e) => edgeMap.set(edgeKey(e), e))
    before.edges.forEach((e) => {
        if (!edgeMap.has(edgeKey(e))) {
            edgeMap.set(edgeKey(e), e)
        }
    })
    const unionEdges = Array.from(edgeMap.values())
    const edgeDiff = new Map<string, DiffStatus>()
    unionEdges.forEach((e) => {
        const key = edgeKey(e)
        if (beforeEdgeKeys.has(key) && afterEdgeKeys.has(key)) {
            edgeDiff.set(key, 'kept')
        } else if (afterEdgeKeys.has(key)) {
            edgeDiff.set(key, 'added')
        } else {
            edgeDiff.set(key, 'removed')
        }
    })

    return { unionGraph: { nodes: unionNodes, edges: unionEdges }, nodeDiff, edgeDiff }
}
