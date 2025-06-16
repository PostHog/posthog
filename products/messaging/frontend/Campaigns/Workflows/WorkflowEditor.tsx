import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    getConnectedEdges,
    getIncomers,
    getOutgoers,
    Node,
    ReactFlow,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { OnWorkflowChange } from '../campaignLogic'
import { getFormattedNodes } from './autolayout'
import { getDefaultEdgeOptions } from './constants'
import { NodeDetailsPanel } from './Nodes/NodeDetailsPanel'
import { DROPZONE_NODE_TYPES, REACT_FLOW_NODE_TYPES } from './Nodes/Nodes'
import {
    addDropzoneNodes,
    createEdgesForNewNode,
    createNewNode,
    getEdgesFromHogFlow,
    getNodesFromHogFlow,
} from './Nodes/utils'
import { Toolbar, ToolbarNode } from './Toolbar'
import type { HogFlow, HogFlowAction, HogFlowEdge } from './types'

// Inner component that encapsulates React Flow
function WorkflowEditorContent({
    initialValues,
    onChange,
}: {
    initialValues: HogFlow
    onChange: OnWorkflowChange
}): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const initialNodes = useMemo(() => getNodesFromHogFlow(initialValues), [initialValues])
    const initialEdges = useMemo(() => getEdgesFromHogFlow(initialValues), [initialValues])

    const [nodes, setNodes, onNodesChange] = useNodesState<Node<HogFlowAction>>(initialNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<HogFlowEdge>>(initialEdges)

    useEffect(() => {
        onChange({
            actions: nodes.map((node) => node.data),
            edges: edges.map((edge) => ({
                from: edge.source,
                to: edge.target,
                // TODO(team-messaging): Decide if we need this edge type
                type: 'continue',
                index: edge.data?.index || 0,
            })),
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodes.length, edges.length])

    const reactFlowWrapper = useRef<HTMLDivElement>(null)

    const [toolbarNodeUsed, setToolbarNodeUsed] = useState<ToolbarNode>()
    const [selectedNode, setSelectedNode] = useState<Node<HogFlowAction>>()

    const { screenToFlowPosition, deleteElements, setCenter, getIntersectingNodes, fitView } = useReactFlow()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

    const updateAndLayout = useCallback(
        async ({ nodes, edges }) => {
            void (async () => {
                const formattedNodes = await getFormattedNodes(nodes, edges)
                setNodes(formattedNodes)
                setEdges(edges)
                void fitView()
            })()
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    // Layout the graph on mount.
    useLayoutEffect(() => {
        void updateAndLayout({ nodes: initialNodes, edges: initialEdges })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // When a node is selected, center the view on it
    useEffect(() => {
        if (selectedNode) {
            void setCenter(
                (selectedNode?.position.x || 0) + (selectedNode?.measured?.width || 0) / 2,
                (selectedNode?.position.y || 0) + 100,
                {
                    duration: 300,
                    zoom: 2,
                }
            )
        }
    }, [selectedNode, setCenter])

    const findIntersectingDropzone = useCallback(
        (event: React.DragEvent): Node<HogFlowAction> | undefined => {
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
            return intersectingDropzoneNode as Node<HogFlowAction> | undefined
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
            const edgeIdToInsertNodeInto = intersectingDropzone?.id.replace('dropzone_edge_', '')
            const edgeToInsertNodeInto = edges.find((edge) => edge.id === edgeIdToInsertNodeInto)

            const updatedNodes = [...nodes.filter((nd) => !DROPZONE_NODE_TYPES.includes(nd.type || ''))]

            if (!toolbarNodeUsed || !intersectingDropzone || !edgeToInsertNodeInto) {
                setNodes(updatedNodes)
                return
            }

            // Create the new node in the position of the dropzone
            const newNodeId = `${toolbarNodeUsed.type}_${Date.now()}`
            const newNode = createNewNode(toolbarNodeUsed, newNodeId, {
                x: intersectingDropzone.position.x,
                y: intersectingDropzone.position.y,
            })
            updatedNodes.push({ ...newNode })

            // Create incoming and outgoing edges for the new node, and remove the edge that was inserted into
            const updatedEdges = [...edges.filter((edge) => edge.id !== edgeIdToInsertNodeInto)]
            const newEdges = createEdgesForNewNode(newNodeId, toolbarNodeUsed.type, edgeToInsertNodeInto)
            updatedEdges.push(...newEdges)

            void updateAndLayout({ nodes: updatedNodes, edges: updatedEdges })
        },
        [findIntersectingDropzone, edges, nodes, toolbarNodeUsed, updateAndLayout, setNodes]
    )

    // When a node is deleted, connect the middle nodes to their incomers and outgoers to avoid orphaned nodes
    const onNodesDelete = useCallback(
        (deleted: Node<HogFlowAction>[]) => {
            // Hide node details if any deleted node is the selected node
            if (deleted.some((node) => node.id === selectedNode?.id)) {
                setSelectedNode(undefined)
            }

            // Connect middle nodes to their incomers and outgoers to avoid orphaned nodes
            const newEdges = deleted.reduce((acc, node) => {
                const incomers = getIncomers(node, nodes, edges)
                const outgoers = getOutgoers(node, nodes, edges)
                const connectedEdges = getConnectedEdges([node], edges)

                const sourceHandle = connectedEdges.find((e) => e.target === node.id)?.sourceHandle
                const sourceLabel = connectedEdges.find((e) => e.target === node.id)?.label
                const targetHandle = connectedEdges.find((e) => e.source === node.id)?.targetHandle

                const remainingEdges = acc.filter((edge) => !connectedEdges.includes(edge))

                const createdEdges = incomers.flatMap(({ id: source }) =>
                    outgoers.map(({ id: target }) => ({
                        id: `${source}->${target}${sourceHandle ? `:${sourceHandle}` : ''}`,
                        source,
                        target,
                        sourceHandle,
                        targetHandle,
                        label: sourceLabel,
                        ...getDefaultEdgeOptions(),
                    }))
                )

                return [...remainingEdges, ...createdEdges]
            }, edges)

            const newNodes = nodes.filter((node) => !deleted.includes(node))

            void updateAndLayout({ nodes: newNodes, edges: newEdges })
        },
        [nodes, edges, selectedNode?.id, setSelectedNode, updateAndLayout]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow<Node<HogFlowAction>, Edge<HogFlowEdge>>
                fitView
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={() => {
                    setNodes(addDropzoneNodes(nodes, edges))
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

// TODO: Set up workflow update callback
export function WorkflowEditor({
    initialValues,
    onChange,
}: {
    initialValues: HogFlow
    onChange: OnWorkflowChange
}): JSX.Element {
    return (
        <ReactFlowProvider>
            <WorkflowEditorContent initialValues={initialValues} onChange={onChange} />
        </ReactFlowProvider>
    )
}
