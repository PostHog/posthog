import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    Node,
    ReactFlow,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { OnWorkflowChange } from '../campaignLogic'
import { ActionDetailsPanel } from './actions/ActionDetailsPanel'
import { HogFlowActionManager } from './actions/hogFlowActionManager'
import { REACT_FLOW_NODE_TYPES } from './actions/Nodes'
import { getFormattedNodes } from './autolayout'
import { HogflowTestPanel } from './testing/HogFlowTestPanel'
import { Toolbar, ToolbarNode } from './Toolbar'
import type { HogFlow, HogFlowAction } from './types'

// Inner component that encapsulates React Flow
function HogFlowEditorContent({ hogFlow, onChange }: { hogFlow: HogFlow; onChange: OnWorkflowChange }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes: parsedNodes, edges: parsedEdges } = useMemo(
        () => HogFlowActionManager.getReactFlowFromHogFlow(hogFlow),
        [hogFlow]
    )
    const [nodes, setNodes, onNodesChange] = useNodesState<Node<HogFlowAction>>(parsedNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(parsedEdges)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)

    const [toolbarNodeUsed, setToolbarNodeUsed] = useState<ToolbarNode>()
    const [selectedNode, setSelectedNode] = useState<Node<HogFlowAction>>()
    const { screenToFlowPosition, deleteElements, getIntersectingNodes, fitView } = useReactFlow()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

    // Layout the graph on node changes.
    useEffect(() => {
        void (async () => {
            const { nodes, edges } = HogFlowActionManager.getReactFlowFromHogFlow(hogFlow)
            const formattedNodes = await getFormattedNodes(nodes)
            setNodes(formattedNodes)
            setEdges(edges)
        })()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hogFlow.actions])

    // Center content whenever nodes positions change
    useEffect(() => {
        void fitView()
    }, [fitView, nodes])

    const onNodesDelete = useCallback(
        (deleted: Node<HogFlowAction>[]) => {
            // Hide node details if any deleted node is the selected node
            if (deleted.some((node) => node.id === selectedNode?.id)) {
                setSelectedNode(undefined)
            }

            const updatedActions = HogFlowActionManager.deleteActions(deleted, hogFlow)
            onChange({ actions: updatedActions })
        },
        [hogFlow, selectedNode?.id, setSelectedNode, onChange]
    )

    const onDragStart = useCallback(() => {
        setNodes(HogFlowActionManager.addDropzoneNodes(nodes, edges))
    }, [nodes, edges, setNodes])

    const onDragOver = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'

            setNodes((nds) =>
                HogFlowActionManager.highlightDropzoneNodes(nds, event, screenToFlowPosition, getIntersectingNodes)
            )
        },
        [screenToFlowPosition, getIntersectingNodes, setNodes]
    )

    const onDrop = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault()

            const intersectingDropzone = HogFlowActionManager.findIntersectingDropzone(
                event,
                screenToFlowPosition,
                getIntersectingNodes
            )
            if (!toolbarNodeUsed || !intersectingDropzone) {
                // No changes, just hide dropzones
                setNodes((nds) => HogFlowActionManager.removeDropzoneNodes(nds))
                return
            }

            // Create the new node in the position of the dropzone using the manager
            const updatedActions = HogFlowActionManager.insertNodeIntoDropzone(
                hogFlow.actions,
                toolbarNodeUsed,
                intersectingDropzone
            )
            onChange({ actions: updatedActions })
        },
        [screenToFlowPosition, getIntersectingNodes, toolbarNodeUsed, hogFlow.actions, onChange, setNodes]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow<Node<HogFlowAction>, Edge>
                fitView
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onNodeClick={(_, node) => node.selectable && setSelectedNode(node)}
                onDrop={onDrop}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
            >
                <Controls showInteractive={false} />

                <Background gap={36} variant={BackgroundVariant.Dots} />

                <Toolbar setNewNode={setToolbarNodeUsed} />

                {selectedNode && (
                    <ActionDetailsPanel
                        node={selectedNode}
                        onChange={(node) => setNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)))}
                        onDelete={(node) => {
                            void deleteElements({ nodes: [node] })
                        }}
                        onClose={() => setSelectedNode(undefined)}
                    />
                )}

                <HogflowTestPanel hogFlow={hogFlow} />
            </ReactFlow>
        </div>
    )
}

export function HogFlowEditor({ hogFlow, onChange }: { hogFlow: HogFlow; onChange: OnWorkflowChange }): JSX.Element {
    return (
        <ReactFlowProvider>
            <HogFlowEditorContent hogFlow={hogFlow} onChange={onChange} />
        </ReactFlowProvider>
    )
}
