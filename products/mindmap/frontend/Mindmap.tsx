import '@xyflow/react/dist/style.css'
import './styles.scss'

import { Background, Controls, Edge as XyEdge, Node as XyNode, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { mindmapLogic } from './mindmapLogic'
import { PostItNode, PostItNodeData } from './PostItNode'

const NODE_TYPES = { postit: PostItNode }

function MindmapInner(): JSX.Element {
    const { postits, edges } = useValues(mindmapLogic)
    const { startPolling, stopPolling, nodeDragged } = useActions(mindmapLogic)

    useEffect(() => {
        startPolling()
        return () => stopPolling()
    }, [startPolling, stopPolling])

    const nodes: XyNode<PostItNodeData>[] = useMemo(
        () =>
            postits.map((p) => ({
                id: p.short_id,
                type: 'postit',
                position: { x: p.position_x, y: p.position_y },
                data: {
                    short_id: p.short_id,
                    title: p.title,
                    body: p.body ?? '',
                    color: p.color,
                    emoji: p.emoji ?? '',
                    notebook_short_id: p.notebook_short_id ?? null,
                },
            })),
        [postits]
    )

    const flowEdges: XyEdge[] = useMemo(
        () =>
            edges.map((e, i) => ({
                id: `${e.source}->${e.target}-${i}`,
                source: e.source,
                target: e.target,
            })),
        [edges]
    )

    if (postits.length === 0) {
        return (
            <div className="flex items-center justify-center h-full w-full text-center text-gray-500">
                <div>
                    <h3 className="text-lg font-semibold mb-2">Your team's mindmap is empty</h3>
                    <p>Ask Max to add post-its.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="w-full h-full">
            <ReactFlow
                nodes={nodes}
                edges={flowEdges}
                nodeTypes={NODE_TYPES}
                onNodeDragStop={(_, node) => nodeDragged(node.id, node.position.x, node.position.y)}
                fitView
            >
                <Background />
                <Controls />
            </ReactFlow>
        </div>
    )
}

export function Mindmap(): JSX.Element {
    return (
        <ReactFlowProvider>
            <MindmapInner />
        </ReactFlowProvider>
    )
}
