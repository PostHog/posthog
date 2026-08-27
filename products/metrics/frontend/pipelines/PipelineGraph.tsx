import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { edgeKey, pipelineGraphLogic } from './pipelineGraphLogic'
import { PIPELINE_NODE_TYPES, PipelineNodeCardData } from './PipelineNodeCard'
import { PipelineConfigType, PipelineEvaluationType, PipelineNodeType, formatStatValue } from './types'

export interface PipelineGraphProps {
    config: PipelineConfigType
    evaluation: PipelineEvaluationType | null
    selectedNodeId: string | null
    selectedEdgeKey: string | null
    onSelectNode: (nodeId: string | null) => void
    onSelectEdge: (edgeKey: string | null) => void
}

function PipelineGraphContent(props: PipelineGraphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { layout } = useValues(pipelineGraphLogic({ nodes: props.config.nodes, edges: props.config.edges }))

    if (!layout) {
        return (
            <div className="flex items-center justify-center w-full h-full">
                <Spinner />
            </div>
        )
    }

    const resultsByNode = Object.fromEntries((props.evaluation?.nodes ?? []).map((node) => [node.id, node]))
    const resultsByEdge = Object.fromEntries(
        (props.evaluation?.edges ?? []).map((edge) => [`${edge.source}>${edge.target}`, edge])
    )

    // Cheap per-render pass: verdicts, selection, and click handlers change
    // without retriggering the ELK layout.
    const decoratedNodes = layout.nodes.map((rfNode) => {
        const node = (rfNode.data as PipelineNodeCardData).node as PipelineNodeType
        return {
            ...rfNode,
            data: {
                ...rfNode.data,
                result: resultsByNode[node.id],
                isSelected: node.id === props.selectedNodeId,
                onClick: () => props.onSelectNode(node.id),
            } as PipelineNodeCardData,
        }
    })

    const decoratedEdges = layout.edges.map((rfEdge) => {
        const result = resultsByEdge[rfEdge.id]
        const hot = result?.hot ?? false
        const multiplier = result?.multiplier ?? null
        const strokeWidth = multiplier === null ? 1.5 : Math.max(1.5, Math.min(8, 1.5 + (multiplier - 1) * 2))
        const label =
            result && result.current_value !== null
                ? `${multiplier === null ? 'new' : `${multiplier.toFixed(1)}×`} · ${formatStatValue(result.current_value, 'rate')}`
                : undefined
        return {
            ...rfEdge,
            animated: true,
            label,
            selected: rfEdge.id === props.selectedEdgeKey,
            style: { stroke: hot ? 'var(--warning)' : 'var(--muted)', strokeWidth },
            labelStyle: { fontSize: 10, fontFamily: 'var(--font-mono)' },
        }
    })

    return (
        <ReactFlow
            colorMode={isDarkModeOn ? 'dark' : 'light'}
            nodes={decoratedNodes}
            edges={decoratedEdges}
            nodeTypes={PIPELINE_NODE_TYPES}
            nodesDraggable={false}
            nodesConnectable={false}
            fitView
            minZoom={0.2}
            maxZoom={2}
            zoomOnScroll
            panOnScroll
            zoomOnPinch
            onEdgeClick={(_, edge) => props.onSelectEdge(edge.id)}
            onPaneClick={() => {
                props.onSelectNode(null)
                props.onSelectEdge(null)
            }}
            proOptions={{ hideAttribution: true }}
        >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
    )
}

export function PipelineGraph(props: PipelineGraphProps): JSX.Element {
    if (props.config.nodes.length === 0) {
        return (
            <div className="flex items-center justify-center w-full h-full text-muted text-sm">
                This pipeline has no nodes yet — edit it to add some.
            </div>
        )
    }
    return (
        <ReactFlowProvider>
            <PipelineGraphContent {...props} />
        </ReactFlowProvider>
    )
}

export { edgeKey }
