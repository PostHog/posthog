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
import { HogFlowActionManager } from './actions/hogFlowActionManager'
import { NodeDetailsPanel } from './actions/NodeDetailsPanel'
import { DROPZONE_NODE_TYPES, REACT_FLOW_NODE_TYPES } from './actions/Nodes'
import { getFormattedNodes } from './autolayout'
import { Toolbar, ToolbarNode } from './Toolbar'
import type { HogFlow, HogFlowAction } from './types'

// Inner component that encapsulates React Flow
function HogFlowEditorContent({ hogFlow, onChange }: { hogFlow: HogFlow; onChange: OnWorkflowChange }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [nodes, setNodes, onNodesChange] = useNodesState<Node<HogFlowAction>>(
        HogFlowActionManager.getNodesFromHogFlow(hogFlow)
    )
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(HogFlowActionManager.getEdgesFromHogFlow(hogFlow))

    const reactFlowWrapper = useRef<HTMLDivElement>(null)

    const [toolbarNodeUsed, setToolbarNodeUsed] = useState<ToolbarNode>()
    const [selectedNode, setSelectedNode] = useState<Node<HogFlowAction>>()
    const { screenToFlowPosition, deleteElements, getIntersectingNodes, fitView } = useReactFlow()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

    // Layout the graph on node changes.
    useEffect(() => {
        void (async () => {
            const formattedNodes = await getFormattedNodes(HogFlowActionManager.getNodesFromHogFlow(hogFlow))
            setNodes(formattedNodes)
            setEdges(HogFlowActionManager.getEdgesFromHogFlow(hogFlow))
        })()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hogFlow.actions])

    // Center content whenever nodes positions change
    useEffect(() => {
        void fitView()
    }, [fitView, nodes])

    const findIntersectingDropzone = useCallback(
        (event: React.DragEvent): Node<{ edge: Edge }> | undefined => {
            const position = screenToFlowPosition({
                x: event.clientX,
                y: event.clientY,
            })
            const intersectingNodes = getIntersectingNodes(
                // an arbitrary rect to use for intersection detection
                {
                    x: position.x,
                    y: position.y,
                    width: 10,
                    height: 10,
                },
                true // enable partial intersections
            )

            const intersectingDropzoneNode = intersectingNodes.find((node) =>
                DROPZONE_NODE_TYPES.includes(node.type || '')
            )
            return intersectingDropzoneNode as Node<{ edge: Edge }> | undefined
        },
        [getIntersectingNodes, screenToFlowPosition]
    )

    // Update the highlighted dropzone every time a user's dragged node changes position
    const onDragOver = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'

            const intersectingDropzone = findIntersectingDropzone(event)

            setNodes((nds) =>
                nds.map((nd) => {
                    if (!DROPZONE_NODE_TYPES.includes(nd.type || '')) {
                        return nd
                    }
                    return { ...nd, type: nd.id === intersectingDropzone?.id ? 'dropzone_highlighted' : 'dropzone' }
                })
            )
        },
        [findIntersectingDropzone, setNodes]
    )

    // When a user drops a node into the workflow, create a new node and connect it into the edge that was inserted into
    const onDrop = useCallback(
        async (event) => {
            event.preventDefault()

            const intersectingDropzone = findIntersectingDropzone(event)
            if (!toolbarNodeUsed || !intersectingDropzone) {
                // No changes, just hide dropzones
                setNodes([...nodes.filter((nd) => !DROPZONE_NODE_TYPES.includes(nd.type || ''))])
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
        [findIntersectingDropzone, toolbarNodeUsed, hogFlow.actions, onChange, setNodes, nodes]
    )

    // When a node is deleted, connect the middle nodes to their incomers and outgoers to avoid orphaned nodes
    const onNodesDelete = useCallback(
        (deleted: Node<HogFlowAction>[]) => {
            // Hide node details if any deleted node is the selected node
            if (deleted.some((node) => node.id === selectedNode?.id)) {
                setSelectedNode(undefined)
            }

            // Get the nodes that are incoming to the deleted nodes, and connect them to their deleted nodes' continue next action
            const deletedNodeIds = deleted.map((node) => node.id)
            const updatedActions = hogFlow.actions
                .filter((action) => !deletedNodeIds.includes(action.id))
                .map((action) => {
                    // For each action, update its next_actions to skip deleted nodes
                    const updatedNextActions: Record<string, { action_id: string; label?: string }> = {}

                    Object.entries(action.next_actions).forEach(([branch, nextAction]) => {
                        if (deletedNodeIds.includes(nextAction.action_id)) {
                            // Find the deleted node's continue action and use that instead
                            const deletedNode = hogFlow.actions.find((a) => a.id === nextAction.action_id)
                            if (deletedNode?.next_actions.continue) {
                                updatedNextActions[branch] = deletedNode.next_actions.continue
                            }
                        } else {
                            updatedNextActions[branch] = nextAction
                        }
                    })

                    return {
                        ...action,
                        next_actions: updatedNextActions,
                    }
                })

            onChange({ actions: updatedActions })
        },
        [hogFlow.actions, selectedNode?.id, setSelectedNode, onChange]
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
                onDragStart={() => {
                    setNodes(HogFlowActionManager.addDropzoneNodes(nodes, edges))
                }}
                onDragOver={onDragOver}
                onNodeClick={(_, node) => {
                    if (node.selectable) {
                        setSelectedNode(node)
                    }
                }}
                onDrop={(event) => {
                    void onDrop(event)
                }}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
            >
                {/* Since nodes are not draggable, we don't need the interactive controls */}
                <Controls showInteractive={false} />

                <Background gap={36} variant={BackgroundVariant.Dots} />

                <Toolbar setNewNode={setToolbarNodeUsed} />

                {selectedNode && (
                    <NodeDetailsPanel
                        node={selectedNode}
                        onChange={(node) => setNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)))}
                        onDelete={(node) => {
                            void deleteElements({ nodes: [node] })
                        }}
                        onClose={() => setSelectedNode(undefined)}
                    />
                )}
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
