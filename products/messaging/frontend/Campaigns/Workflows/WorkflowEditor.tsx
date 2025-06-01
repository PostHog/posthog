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
    getSmoothStepPath,
    Node,
    Panel,
    Position,
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
import {
    createEdgesForNewNode,
    createNewNode,
    DEFAULT_EDGES,
    DEFAULT_NODES,
    NODE_HEIGHT,
    NODE_WIDTH,
} from './nodeUtils'
import { StepDetailsPanel } from './StepDetails'

// Node types available for adding to the flow
const TOOLBAR_NODES = [
    { type: 'email', label: 'Email', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Wait', icon: <IconHourglass /> },
    { type: 'delay_until', label: 'Wait until', icon: <IconRevert /> },
] as const
export type ToolbarNode = (typeof TOOLBAR_NODES)[number]

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
                <h3 className="font-semibold nodrag">Workflow steps</h3>
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
    const [toolbarNodeUsed, setToolbarNodeUsed] = useState<ToolbarNode>()
    const [selectedNode, setSelectedNode] = useState<Node<WorkflowNodeData>>()

    const onChange = useCallback(({ nodes }) => {
        setSelectedNode(nodes.length ? nodes[0] : undefined)
    }, [])

    useOnSelectionChange({
        onChange,
    })

    const { screenToFlowPosition, deleteElements, setCenter, getIntersectingNodes } = useReactFlow()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

    const updateAndLayout = useCallback(({ nodes, edges }) => {
        void (async () => {
            const layoutedNodes = await getFormattedNodes(nodes, edges)
            setNodes(layoutedNodes)
            setEdges(edges)
        })()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
        void updateAndLayout({ nodes, edges })
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

    const addDropzoneNodes = (
        nodes: Node<WorkflowNodeData>[],
        edges: Edge<WorkflowEdgeData>[]
    ): Node<WorkflowNodeData>[] => {
        const newNodes = [...nodes]

        edges.forEach((edge) => {
            const sourceNode = nodes.find((n) => n.id === edge.source)
            const targetNode = nodes.find((n) => n.id === edge.target)

            if (sourceNode && targetNode) {
                const sourceHandle = sourceNode.handles?.find((h) => h.id === edge.sourceHandle)
                const targetHandle = targetNode.handles?.find((h) => h.id === edge.targetHandle)

                // Get the path points using getSmoothStepPath
                const [, labelX, labelY] = getSmoothStepPath({
                    sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                    sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                    targetX: targetNode.position.x + (targetHandle?.x || 0),
                    targetY: targetNode.position.y + (targetHandle?.y || 0),
                    sourcePosition: sourceHandle?.position || Position.Bottom,
                    targetPosition: targetHandle?.position || Position.Top,
                })

                // labelx and labely are the x and y coordinates of the label, but we need to adjust them to be relative to the node

                // Create dropzone node
                const dropzoneId = `dropzone_edge_${edge.id}`
                newNodes.push({
                    id: dropzoneId,
                    type: 'dropzone',
                    position: { x: labelX - NODE_WIDTH / 2, y: labelY - NODE_HEIGHT / 2 },
                    data: { label: '', description: '', config: null },
                    draggable: false,
                    selectable: false,
                })
            }
        })

        return newNodes
    }

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

    const onDragOver = useCallback(
        (event: React.DragEvent) => {
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
        },
        [findIntersectingDropzone, setNodes]
    )

    const onDrop = useCallback(
        (event) => {
            event.preventDefault()
            const intersectingDropzone = findIntersectingDropzone(event)
            const edgeIdToInsertNodeInto = intersectingDropzone?.id.replace('dropzone_edge_', '')
            const edgeToInsertNodeInto = edges.find((edge) => edge.id === edgeIdToInsertNodeInto)

            const updatedNodes = [
                ...nodes.filter((nd) => !['dropzone', 'dropzone_highlighted'].includes(nd.type || '')),
            ]

            if (!toolbarNodeUsed || !intersectingDropzone || !edgeToInsertNodeInto) {
                setNodes(updatedNodes)
                return
            }

            const updatedEdges = [...edges.filter((edge) => edge.id !== edgeIdToInsertNodeInto)]

            const newNodeId = `${toolbarNodeUsed.type}_${Date.now()}`
            const newNode = createNewNode(toolbarNodeUsed, newNodeId, {
                x: intersectingDropzone.position.x,
                y: intersectingDropzone.position.y,
            })
            updatedNodes.push(newNode)

            const newEdges = createEdgesForNewNode(newNodeId, toolbarNodeUsed.type, edgeToInsertNodeInto)

            updatedEdges.push(...newEdges)

            void updateAndLayout({ nodes: updatedNodes, edges: updatedEdges })
            setSelectedNode(newNode)
        },
        [findIntersectingDropzone, edges, nodes, toolbarNodeUsed, updateAndLayout, setNodes]
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
                        // TODO: Replace this with edge creator from nodeUtils
                        id: `${source}->${target}`,
                        source,
                        target,
                        type: 'smoothstep',
                    }))
                )

                return [...remainingEdges, ...createdEdges]
            }, edges)

            void updateAndLayout({ nodes: nodes.filter((node) => !deleted.includes(node)), edges: newEdges })
        },
        [nodes, edges, selectedNode?.id, setSelectedNode, updateAndLayout]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow<Node<WorkflowNodeData>, Edge<WorkflowEdgeData>>
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
                onDrop={onDrop}
                nodeTypes={nodeTypes}
                // nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                fitView
            >
                <Controls showInteractive={false} />
                <Background gap={36} variant={BackgroundVariant.Dots} />

                <Toolbar setNewNode={setToolbarNodeUsed} />

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
