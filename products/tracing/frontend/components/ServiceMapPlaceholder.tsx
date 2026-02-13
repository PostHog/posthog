import '@xyflow/react/dist/style.css'

import dagre from '@dagrejs/dagre'
import {
    Background,
    BackgroundVariant,
    Controls,
    type Edge,
    Handle,
    MarkerType,
    MiniMap,
    type Node,
    type NodeTypes,
    Position,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import React, { useEffect, useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import type { ServiceEdgeData, ServiceNodeData } from '../data/mockServiceMapData'
import { MOCK_SERVICE_GRAPH } from '../data/mockServiceMapData'
import { tracingSceneLogic } from '../tracingSceneLogic'

const NODE_WIDTH = 220
const NODE_HEIGHT = 80
const NODE_SEP = 60
const RANK_SEP = 140
const MARKER_SIZE = 16

interface ServiceNodeProps {
    data: ServiceNodeData & { color: string }
}

function ServiceNode({ data }: ServiceNodeProps): JSX.Element {
    const errorRate = data.span_count > 0 ? Math.round((data.error_count / data.span_count) * 100) : 0

    return (
        <div
            className="bg-bg-light border rounded-md p-3 shadow-sm"
            style={{ borderColor: data.color, borderWidth: 2, minWidth: NODE_WIDTH }}
        >
            <Handle type="target" position={Position.Left} className="w-2 h-2" style={{ background: data.color }} />

            <div className="font-semibold text-sm mb-1 truncate">{data.id}</div>
            <div className="flex items-center gap-2 text-xs">
                <span className="text-muted">{data.trace_count} traces</span>
                <span className="text-muted">{data.span_count} spans</span>
                {errorRate > 0 ? (
                    <LemonTag type="danger" size="small">
                        {errorRate}% errors
                    </LemonTag>
                ) : (
                    <LemonTag type="success" size="small">
                        0% errors
                    </LemonTag>
                )}
            </div>

            <Handle type="source" position={Position.Right} className="w-2 h-2" style={{ background: data.color }} />
        </div>
    )
}

const nodeTypes: NodeTypes = {
    serviceNode: ServiceNode,
}

// --- Layout ---

function getLayoutedElements(
    serviceNodes: ServiceNodeData[],
    serviceEdges: ServiceEdgeData[]
): { nodes: Node[]; edges: Edge[] } {
    const dagreGraph = new dagre.graphlib.Graph()
    dagreGraph.setDefaultEdgeLabel(() => ({}))
    dagreGraph.setGraph({ rankdir: 'LR', nodesep: NODE_SEP, ranksep: RANK_SEP })

    serviceNodes.forEach((node) => {
        dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
    })
    serviceEdges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target)
    })
    dagre.layout(dagreGraph)

    const colorMap = new Map<string, string>()
    serviceNodes.forEach((node, i) => {
        colorMap.set(node.id, getSeriesColor(i))
    })

    const nodes: Node[] = serviceNodes.map((node) => {
        const pos = dagreGraph.node(node.id)
        return {
            id: node.id,
            type: 'serviceNode',
            position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
            data: { ...node, color: colorMap.get(node.id) ?? getSeriesColor(0) },
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
        }
    })

    const edges: Edge[] = serviceEdges.map((edge, i) => ({
        id: `edge-${i}`,
        source: edge.source,
        target: edge.target,
        type: 'default',
        animated: false,
        label: `${edge.request_count}`,
        markerEnd: {
            type: MarkerType.ArrowClosed,
            width: MARKER_SIZE,
            height: MARKER_SIZE,
        },
        data: edge,
    }))

    return { nodes, edges }
}

function ServiceMapContent(): JSX.Element {
    const { fitView } = useReactFlow()
    const { isDarkModeOn } = useValues(themeLogic)
    const { hoveredServiceNodeId } = useValues(tracingSceneLogic)
    const { setHoveredServiceNodeId } = useActions(tracingSceneLogic)

    const { nodes, edges } = useMemo(() => getLayoutedElements(MOCK_SERVICE_GRAPH.nodes, MOCK_SERVICE_GRAPH.edges), [])

    const styledEdges: Edge[] = edges.map((edge) => {
        const isHighlighted = edge.source === hoveredServiceNodeId || edge.target === hoveredServiceNodeId
        const edgeData = edge.data as ServiceEdgeData | undefined
        const hasErrors = (edgeData?.error_count ?? 0) > 0

        return {
            ...edge,
            style: {
                stroke: isHighlighted ? (hasErrors ? 'var(--danger)' : 'var(--primary)') : undefined,
                strokeWidth: isHighlighted ? 2 : 1,
            },
            labelStyle: {
                fontWeight: isHighlighted ? 600 : 400,
                fontSize: 12,
            },
            markerEnd: {
                type: MarkerType.ArrowClosed,
                width: MARKER_SIZE,
                height: MARKER_SIZE,
                ...(isHighlighted ? { color: hasErrors ? 'var(--danger)' : 'var(--primary)' } : {}),
            },
        }
    })

    const onNodeMouseEnter = (_e: React.MouseEvent, node: Node): void => setHoveredServiceNodeId(node.id)
    const onNodeMouseLeave = (): void => setHoveredServiceNodeId(null)

    useEffect(() => {
        let timeoutId: ReturnType<typeof setTimeout> | null = null
        if (nodes.length > 0) {
            timeoutId = setTimeout(() => fitView({ padding: 0.2 }), 100)
        }
        return () => {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
        }
    }, [nodes, fitView])

    return (
        <div className="w-full h-full">
            <ReactFlow
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={nodes}
                edges={styledEdges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                minZoom={0.3}
                maxZoom={2}
                onNodeMouseEnter={onNodeMouseEnter}
                onNodeMouseLeave={onNodeMouseLeave}
            >
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                <Controls showInteractive={false} position="bottom-right" />
                <MiniMap zoomable pannable position="bottom-left" nodeStrokeWidth={2} className="hidden lg:block" />
            </ReactFlow>
        </div>
    )
}

export function ServiceMapPlaceholder(): JSX.Element {
    return (
        <div className="grow border border-border rounded-md overflow-hidden">
            <ReactFlowProvider>
                <ServiceMapContent />
            </ReactFlowProvider>
        </div>
    )
}
