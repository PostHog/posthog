import '@xyflow/react/dist/style.css'

import { IconDecisionTree, IconHourglass, IconRevert, IconSend } from '@posthog/icons'
import { WorkflowEdge, WorkflowEdgeData, WorkflowNode, WorkflowNodeData } from '@posthog/workflows'
import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    getConnectedEdges,
    getIncomers,
    getOutgoers,
    MiniMap,
    Node,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
    useOnSelectionChange,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { getFormattedNodes } from './formatter'
import { REACT_FLOW_NODE_TYPES } from './Nodes'
import { StepDetailsPanel } from './StepDetails'

// Initial node setup - just one starting node
const DEFAULT_NODES: Node<WorkflowNodeData>[] = [
    {
        id: 'trigger_node',
        type: 'trigger',
        data: { label: 'Trigger', description: '', config: null },
        position: { x: 0, y: 0 },
        deletable: false,
        draggable: false,
        selectable: true,
    },
    {
        id: 'exit_node',
        type: 'exit',
        data: { label: 'Exit', description: '', config: null },
        position: { x: 0, y: 100 },
        deletable: false,
        draggable: false,
        selectable: false,
    },
]

// Initial edges setup
const DEFAULT_EDGES: Edge<WorkflowEdgeData>[] = [
    { id: 'trigger_node->exit_node', source: 'trigger_node', target: 'exit_node', type: 'smoothstep' },
]

// Node types available for adding to the flow
const TOOLBAR_NODES = [
    { type: 'email', label: 'Email', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Wait', icon: <IconHourglass /> },
    { type: 'delay_until', label: 'Wait until', icon: <IconRevert /> },
]
type ToolbarNode = (typeof TOOLBAR_NODES)[number]

type WorkflowEditorProps = {
    setWorkflow: ({ nodes, edges }: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }) => void
}

// Draggable node component
function ToolbarNode({
    node,
    setNewNode,
}: {
    node: ToolbarNode
    setNewNode: (nodeType: ToolbarNode) => void
}): JSX.Element {
    const onDragStart = (event: React.DragEvent): void => {
        setNewNode(node)
        event.dataTransfer.setData('application/reactflow', node.type)
        event.dataTransfer.effectAllowed = 'move'
    }

    return (
        <div
            className="bg-surface-primary border rounded flex items-center gap-1 p-2 cursor-grab hover:bg-surface-secondary transition-colors"
            draggable
            onDragStart={onDragStart}
        >
            {node.icon}
            {node.label}
        </div>
    )
}

function Toolbar({ setNewNode }: { setNewNode: (nodeType: ToolbarNode) => void }): JSX.Element {
    return (
        <Panel position="top-left">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col gap-2 p-4 z-10 w-[200px]">
                <h3 className="font-semibold nodrag">Add a step</h3>
                <div className="flex flex-col gap-2">
                    {TOOLBAR_NODES.map((node) => (
                        <ToolbarNode key={node.type} node={node} setNewNode={setNewNode} />
                    ))}
                </div>
            </div>
        </Panel>
    )
}

// Inner component that encapsulates React Flow
function WorkflowEditorContent({ setWorkflow }: WorkflowEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [nodes, setNodes, onNodesChange] = useNodesState<Node<WorkflowNodeData>>(DEFAULT_NODES)
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<WorkflowEdgeData>>(DEFAULT_EDGES)
    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const [newNode, setNewNode] = useState<ToolbarNode>()
    const [selectedNode, setSelectedNode] = useState<Node<WorkflowNodeData>>()

    const onChange = useCallback(({ nodes }) => {
        setSelectedNode(nodes.length ? nodes[0] : undefined)
    }, [])

    useOnSelectionChange({
        onChange,
    })

    const { screenToFlowPosition, deleteElements, setCenter, getIntersectingNodes } = useReactFlow()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

    const onLayout = useCallback(({ nodes, edges }) => {
        void (async () => {
            const layoutedNodes = await getFormattedNodes(nodes, edges)
            setNodes(layoutedNodes)
        })()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Centers on the selected node
    useEffect(() => {
        if (selectedNode) {
            void setCenter(
                selectedNode.position.x + (selectedNode.measured?.width || 0) / 2,
                selectedNode.position.y + 100,
                {
                    duration: 500,
                    zoom: 2,
                }
            )
        }
    }, [setCenter, selectedNode])

    const showDropzones = useCallback(() => {
        const newNodes = [...nodes]
        const newEdges = [...edges]

        edges.forEach((edge) => {
            const sourceNode = nodes.find((n) => n.id === edge.source)
            const targetNode = nodes.find((n) => n.id === edge.target)

            if (sourceNode && targetNode) {
                // Calculate midpoint
                const midX = (sourceNode.position.x + targetNode.position.x) / 2
                const midY = (sourceNode.position.y + targetNode.position.y) / 2

                // Create dropzone node
                const dropzoneId = `dropzone-${edge.id}`
                newNodes.push({
                    id: dropzoneId,
                    type: 'dropzone',
                    position: { x: midX, y: midY },
                    data: { label: '', description: '', config: null },
                    draggable: false,
                    selectable: false,
                })

                // Remove original edge and create two new edges
                newEdges.push(
                    {
                        id: `${edge.source}->${dropzoneId}`,
                        source: edge.source,
                        target: dropzoneId,
                    },
                    {
                        id: `${dropzoneId}->${edge.target}`,
                        source: dropzoneId,
                        target: edge.target,
                    }
                )
            }
        })

        // Remove original edges
        const originalEdgeIds = edges.map((e) => e.id)
        const filteredEdges = newEdges.filter((edge) => !originalEdgeIds.includes(edge.id))

        setNodes(newNodes)
        setEdges(filteredEdges)
    }, [nodes, edges, setEdges, setNodes])

    const hideDropzones = useCallback(() => {
        const dropzoneNodesToDelete = nodes.filter((nd) => ['dropzone', 'dropzone_highlighted'].includes(nd.type || ''))

        // Remove all edges that are connected to dropzone nodes, reconnecting the incomers and outgoers
        setEdges(
            dropzoneNodesToDelete.reduce((acc, node) => {
                const incomers = getIncomers(node, nodes, edges)
                const outgoers = getOutgoers(node, nodes, edges)
                const connectedEdges = getConnectedEdges([node], edges)

                const remainingEdges = acc.filter((edge) => !connectedEdges.includes(edge))

                const createdEdges = incomers.flatMap(({ id: source }) =>
                    outgoers.map(({ id: target }) => ({
                        id: `${source}->${target}`,
                        source,
                        target,
                    }))
                )

                return [...remainingEdges, ...createdEdges]
            }, edges)
        )

        setNodes((nds) => nds.filter((nd) => nd.type !== 'dropzone'))
    }, [edges, nodes, setEdges, setNodes])

    const findIntersectingDropzone = useCallback((event: React.DragEvent): Node<WorkflowNodeData> | undefined => {
        const position = screenToFlowPosition({
            x: event.clientX,
            y: event.clientY,
        })
        const intersectingNodes = getIntersectingNodes(
            {
                x: position.x,
                y: position.y,
                width: 10,
                height: 10,
            },
            true
        )

        const intersectingDropzoneNode = intersectingNodes.find((node) =>
            ['dropzone', 'dropzone_highlighted'].includes(node.type || '')
        )
        return intersectingDropzoneNode as Node<WorkflowNodeData> | undefined
    }, [])

    const onDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'

        const intersectingDropzone = findIntersectingDropzone(event)

        setNodes((nds) =>
            nds.map((nd) => {
                if (!['dropzone', 'dropzone_highlighted'].includes(nd.type || '')) {
                    return nd
                }
                return { ...nd, type: nd.id === intersectingDropzone?.id ? 'dropzone_highlighted' : 'dropzone' }
            })
        )
    }, [])

    const onDrop = useCallback(
        (event) => {
            event.preventDefault()

            if (!newNode) {
                hideDropzones()
                return
            }

            const intersectingDropzone = findIntersectingDropzone(event)
            if (!intersectingDropzone) {
                hideDropzones()
                return
            }

            const updatedNodes = nodes.map((nd) =>
                nd.id === intersectingDropzone?.id
                    ? {
                          ...nd,
                          type: newNode.type,
                          data: { ...nd.data, label: newNode.label, selected: true, selectable: true },
                      }
                    : nd
            )
            // Replace the intersecting dropzone with a real node of the current type.
            setNodes(updatedNodes)

            hideDropzones()
            void onLayout({ nodes: updatedNodes, edges })
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [findIntersectingDropzone, hideDropzones, newNode, setNodes]
    )

    const onNodesDelete = useCallback(
        (deleted: Node<WorkflowNodeData>[]) => {
            // Hide node details if any deleted node is the selected node
            if (deleted.some((node) => node.id === selectedNode?.id)) {
                setSelectedNode(undefined)
            }

            // Connect middle nodes to their incomers and outgoers to avoid orphaned nodes
            const newEdges = deleted.reduce((acc, node) => {
                const incomers = getIncomers(node, nodes, edges)
                const outgoers = getOutgoers(node, nodes, edges)
                const connectedEdges = getConnectedEdges([node], edges)

                const remainingEdges = acc.filter((edge) => !connectedEdges.includes(edge))

                const createdEdges = incomers.flatMap(({ id: source }) =>
                    outgoers.map(({ id: target }) => ({
                        id: `${source}->${target}`,
                        source,
                        target,
                    }))
                )

                return [...remainingEdges, ...createdEdges]
            }, edges)

            setEdges(newEdges)
        },
        [nodes, edges, setEdges, selectedNode?.id, setSelectedNode]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow<Node<WorkflowNodeData>, Edge<WorkflowEdgeData>>
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={showDropzones}
                onDragOver={onDragOver}
                onDragEnd={hideDropzones}
                onNodeClick={(_, node) => {
                    if (node.selectable) {
                        setSelectedNode(node)
                    }
                }}
                onDrop={onDrop}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                fitView
            >
                <Controls showInteractive={false} />
                <Background gap={48} variant={BackgroundVariant.Dots} />

                <MiniMap />

                <Toolbar setNewNode={setNewNode} />

                {selectedNode && (
                    <StepDetailsPanel
                        workflowId="new"
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

export function WorkflowEditor({ setWorkflow }: WorkflowEditorProps): JSX.Element {
    return (
        <ReactFlowProvider>
            <WorkflowEditorContent setWorkflow={setWorkflow} />
        </ReactFlowProvider>
    )
}
