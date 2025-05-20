import '@xyflow/react/dist/style.css'

import { IconDecisionTree, IconHourglass, IconLeave, IconSend, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { WorkflowEdgeData, WorkflowNodeData } from '@posthog/workflows'
import {
    addEdge,
    Background,
    Controls,
    Edge,
    Node,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { capitalizeFirstLetter, Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { nodeDetailsLogic } from './nodeDetailsLogic'
import { REACT_FLOW_EDGE_TYPES, REACT_FLOW_NODE_TYPES } from './Nodes'

// Initial node setup - just one starting node
const initialNodes: Node<WorkflowNodeData>[] = [
    {
        id: 'trigger-node',
        type: 'trigger',
        data: { label: 'Trigger', description: '', config: null },
        position: { x: 250, y: 100 },
        deletable: false,
    },
    {
        id: 'exit-node',
        type: 'exit',
        data: { label: 'Exit', description: '', config: null },
        position: { x: 250, y: 300 },
        deletable: false,
        selectable: false,
    },
]

// Initial edges setup
const initialEdges: Edge<WorkflowEdgeData>[] = [
    { id: 'trigger-node-exit-node', source: 'trigger-node', target: 'exit-node' },
]

// Node types available for adding to the flow
const TOOLBAR_NODE_TYPES = [
    { type: 'email', label: 'Email', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Delay', icon: <IconHourglass /> },
    { type: 'exit', label: 'Exit', icon: <IconLeave /> },
]
type ToolbarNodeType = (typeof TOOLBAR_NODE_TYPES)[number]['type']

const DEFAULT_EDGE_OPTIONS = {
    interactionWidth: 75,
}

type WorkflowEditorProps = {
    setFlowData: ({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) => void
}

// Draggable node component
function ToolbarNode({
    type,
    label,
    icon,
    setNewNodeType,
}: {
    type: ToolbarNodeType
    label: string
    icon: React.ReactNode
    setNewNodeType: (nodeType: ToolbarNodeType) => void
}): JSX.Element {
    const onDragStart = (event: React.DragEvent): void => {
        setNewNodeType(type)
        event.dataTransfer.setData('application/reactflow', type)
        event.dataTransfer.effectAllowed = 'move'
    }

    return (
        <div
            className="bg-surface-primary border rounded flex items-center gap-1 p-2 cursor-grab hover:bg-surface-secondary transition-colors"
            draggable
            onDragStart={onDragStart}
        >
            {icon}
            {label}
        </div>
    )
}

function Toolbar({ setNewNodeType }: { setNewNodeType: (nodeType: ToolbarNodeType) => void }): JSX.Element {
    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col gap-2 p-4 z-10 w-[200px]">
                <h3 className="font-semibold">Drag to add nodes</h3>
                <div className="flex flex-col gap-2">
                    {TOOLBAR_NODE_TYPES.map((type) => (
                        <ToolbarNode
                            key={type.type}
                            type={type.type}
                            label={type.label}
                            icon={type.icon}
                            setNewNodeType={setNewNodeType}
                        />
                    ))}
                </div>
            </div>
        </Panel>
    )
}

function NodeDetailPanel({
    workflowId,
    node,
    onNodeChange,
    onClose,
}: {
    workflowId: string
    node: Node<WorkflowNodeData>
    onNodeChange: (node: Node<WorkflowNodeData>) => void
    onClose: () => void
}): JSX.Element {
    const { nodeDetails } = useValues(
        nodeDetailsLogic({
            workflowId,
            node,
            onNodeChange,
        })
    )
    const reactFlowInstance = useReactFlow()

    const onDelete = useCallback(() => {
        // Get edges connected to this node before deletion
        const connectedEdges = reactFlowInstance.getEdges().filter((e) => e.source === node.id || e.target === node.id)

        // Get the source and target nodes before deletion
        const sourceNodes = connectedEdges
            .filter((e) => e.source !== node.id)
            .map((e) => reactFlowInstance.getNodes().find((n) => n.id === e.source))
            .filter((n): n is Node<WorkflowNodeData> => n !== undefined)
        const targetNodes = connectedEdges
            .filter((e) => e.target !== node.id)
            .map((e) => reactFlowInstance.getNodes().find((n) => n.id === e.target))
            .filter((n): n is Node<WorkflowNodeData> => n !== undefined)

        // Delete the node
        void reactFlowInstance.deleteElements({ nodes: [node] })

        // Create new edges connecting the remaining nodes
        const newEdges = sourceNodes.flatMap((sourceNode) =>
            targetNodes.map((targetNode) => ({
                id: `${sourceNode.id}-${targetNode.id}`,
                source: sourceNode.id,
                target: targetNode.id,
            }))
        )

        // Add the new edges
        if (newEdges.length > 0) {
            reactFlowInstance.addEdges(newEdges)
        }
        onClose()
    }, [node, reactFlowInstance, onClose])

    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 w-[300px]">
                <div className="flex items-center justify-between">
                    <span className="font-semibold text-md">Edit {node.type} node</span>
                    <div className="flex items-center gap-1">
                        <LemonButton size="small" status="danger" onClick={() => onDelete()} icon={<IconTrash />} />
                        <LemonButton size="small" icon={<IconX />} onClick={onClose} aria-label="close" />
                    </div>
                </div>
                <Form logic={nodeDetailsLogic} formKey="node">
                    <LemonField name="label" label="Name">
                        <LemonInput />
                    </LemonField>

                    {node.type === 'trigger' && (
                        <LemonField name="config.triggerType" label="Trigger Type">
                            <LemonSelect
                                options={[
                                    { label: 'Email', value: 'email' },
                                    { label: 'SMS', value: 'sms' },
                                    { label: 'Push', value: 'push' },
                                ]}
                            />
                        </LemonField>
                    )}
                    {node.type === 'action' && (
                        <LemonField name="config.actionType" label="Action Type">
                            <LemonSelect
                                options={[
                                    { label: 'Send Email', value: 'send_email' },
                                    { label: 'Send SMS', value: 'send_sms' },
                                    { label: 'Send Push', value: 'send_push' },
                                ]}
                            />
                        </LemonField>
                    )}
                    {node.type === 'condition' && (
                        <LemonField name="config.conditionType" label="Condition Type">
                            <LemonSelect
                                options={[
                                    { label: 'Has Opened', value: 'has_opened' },
                                    { label: 'Has Clicked', value: 'has_clicked' },
                                    { label: 'Has Responded', value: 'has_responded' },
                                ]}
                            />
                        </LemonField>
                    )}
                </Form>
            </div>
        </Panel>
    )
}

// Inner component that encapsulates React Flow
function WorkflowEditorContent({ setFlowData }: WorkflowEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [nodes, setNodes, onNodesChange] = useNodesState<Node<WorkflowNodeData>>(initialNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<WorkflowEdgeData>>(initialEdges)
    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()
    const [newNodeType, setNewNodeType] = useState<ToolbarNodeType>()
    const [selectedNode, setSelectedNode] = useState<Node<WorkflowNodeData>>()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])
    const edgeTypes = useMemo(() => REACT_FLOW_EDGE_TYPES, [])
    useEffect(() => {
        setFlowData({ nodes, edges })
    }, [nodes, edges, setFlowData])

    const onConnect = useCallback((params) => setEdges((eds) => addEdge(params, eds)), [])

    const onDragOver = useCallback((event) => {
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'

        const edgesWithAddLabels = edges.map((edge) => ({
            ...edge,
            data: { ...edge.data, label: '+' },
        }))

        setEdges(edgesWithAddLabels)
    }, [])

    const onDrop = useCallback(
        (event) => {
            event.preventDefault()

            if (!newNodeType) {
                return
            }

            const position = reactFlowInstance.screenToFlowPosition({
                x: event.clientX - 32,
                y: event.clientY - 32,
            })

            const intersection = reactFlowInstance.getIntersectingNodes({ ...position, width: 100, height: 100 })

            if (intersection.length > 0) {
                return
            }

            const newNode: Node<WorkflowNodeData> = {
                id: `${newNodeType}_${Date.now()}`,
                type: newNodeType,
                position: position,
                data: {
                    label: capitalizeFirstLetter(newNodeType),
                    description: '',
                    config: null,
                },
            }

            const newEdge: Edge<WorkflowEdgeData> = {
                id: `${intersection[0].id}_${newNode.id}`,
                source: intersection[0].id,
                target: newNode.id,
            }

            setNodes((nds) => nds.concat(newNode))
            setEdges((eds) => [...eds, newEdge])
            setSelectedNode(newNode)
        },
        [reactFlowInstance, setNodes, setEdges, newNodeType]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow<Node<WorkflowNodeData>, Edge<WorkflowEdgeData>>
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDragOver={onDragOver}
                onNodeClick={(_, node) => setSelectedNode(node)}
                onDrop={onDrop}
                fitView
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            >
                <Background />
                <Controls />

                {selectedNode ? (
                    <NodeDetailPanel
                        workflowId="new"
                        node={selectedNode}
                        onNodeChange={(node) => setNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)))}
                        onClose={() => setSelectedNode(undefined)}
                    />
                ) : (
                    <Toolbar setNewNodeType={setNewNodeType} />
                )}
            </ReactFlow>
        </div>
    )
}

export function WorkflowEditor({ setFlowData }: WorkflowEditorProps): JSX.Element {
    return (
        <ReactFlowProvider>
            <WorkflowEditorContent setFlowData={setFlowData} />
        </ReactFlowProvider>
    )
}
