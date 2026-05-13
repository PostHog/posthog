import '@xyflow/react/dist/style.css'
import './styles.scss'

import {
    Background,
    Controls,
    Edge as XyEdge,
    Node as XyNode,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { mindmapLogic } from './mindmapLogic'
import { PostItNode, PostItNodeData } from './PostItNode'

const NODE_TYPES = { postit: PostItNode }

interface MindmapProps {
    /** When false, disable drag, pan, zoom, and controls. Post-its remain clickable for notebook navigation. */
    interactive?: boolean
}

function MindmapInner({ interactive }: { interactive: boolean }): JSX.Element {
    const { postits, edges } = useValues(mindmapLogic)
    const { startPolling, stopPolling, nodeDragged } = useActions(mindmapLogic)
    const { fitView } = useReactFlow()

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
                draggable: interactive,
                data: {
                    short_id: p.short_id,
                    title: p.title,
                    body: p.body ?? '',
                    color: p.color,
                    emoji: p.emoji ?? '',
                    notebook_short_id: p.notebook_short_id ?? null,
                },
            })),
        [postits, interactive]
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

    useEffect(() => {
        if (nodes.length === 0) {
            return
        }
        const handle = window.setTimeout(() => fitView({ padding: 0.2, duration: 400 }), 50)
        return () => window.clearTimeout(handle)
    }, [nodes.length, edges.length, fitView])

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
                fitViewOptions={{ padding: 0.2 }}
                nodesDraggable={interactive}
                nodesConnectable={false}
                panOnDrag={interactive}
                zoomOnScroll={interactive}
                zoomOnPinch={interactive}
                zoomOnDoubleClick={interactive}
                proOptions={{ hideAttribution: true }}
            >
                <Background />
                {interactive ? <Controls /> : null}
            </ReactFlow>
        </div>
    )
}

export function Mindmap({ interactive = true }: MindmapProps = {}): JSX.Element {
    return (
        <ReactFlowProvider>
            <MindmapInner interactive={interactive} />
        </ReactFlowProvider>
    )
}
