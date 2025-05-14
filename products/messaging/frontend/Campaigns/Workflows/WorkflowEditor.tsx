import '@xyflow/react/dist/style.css'

import { IconDecisionTree, IconHourglass, IconLeave, IconSend, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { WorkflowEdgeData, WorkflowNodeData } from '@posthog/workflows'
import {
    addEdge,
    Background,
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
import { capitalizeFirstLetter, Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { REACT_FLOW_NODE_TYPES } from './Node'
import { nodeDetailsLogic } from './nodeDetailsLogic'

// Initial node setup - just one starting node
const initialNodes: Node<WorkflowNodeData>[] = [
    {
        id: 'trigger-node',
        type: 'trigger',
        data: { label: 'Trigger', description: '', config: null },
        position: { x: 250, y: 100 },
        selectable: false,
    },
    {
        id: 'exit-node',
        type: 'exit',
        data: { label: 'Exit', description: '', config: null },
        position: { x: 250, y: 300 },
        selectable: false,
    },
]

// Initial edges setup
const initialEdges: Edge<WorkflowEdgeData>[] = [
    { id: 'trigger-node-exit-node', source: 'trigger-node', target: 'exit-node' },
]

// Node types available for adding to the flow
const TOOLBAR_NODE_TYPES = [
    { type: 'message', label: 'Message', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Delay', icon: <IconHourglass /> },
    { type: 'exit', label: 'Exit', icon: <IconLeave /> },
]
type ToolbarNodeType = (typeof TOOLBAR_NODE_TYPES)[number]['type']

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
        <div className="absolute right-4 top-4 bg-surface-primary rounded-md shadow-md flex flex-col gap-2 p-4 z-10 w-[200px]">
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
    )
}

function NodeDetails({
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

    return (
        <div className="absolute right-4 top-4 bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 w-[300px]">
            <div className="flex items-center justify-between">
                <h3 className="font-semibold">Edit {node.type} node</h3>
                <LemonButton size="small" icon={<IconX />} onClick={onClose} aria-label="close" />
            </div>
            <Form logic={nodeDetailsLogic} formKey="node">
                <LemonField name="label" label="Name">
                    <LemonInput />
                </LemonField>

                <LemonField
                    name="description"
                    label="Description"
                    info="Add a description to share context with other team members"
                >
                    <LemonInput />
                </LemonField>
            </Form>
        </div>
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

    useEffect(() => {
        setFlowData({ nodes, edges })
    }, [nodes, edges, setFlowData])

    const onConnect = useCallback((params) => setEdges((eds) => addEdge(params, eds)), [])

    const onDragOver = useCallback((event) => {
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
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
            const newNode: Node<WorkflowNodeData> = {
                id: `${newNodeType}_${Date.now()}`,
                type: newNodeType,
                position,
                data: {
                    label: capitalizeFirstLetter(newNodeType),
                    description: '',
                    config: null,
                },
            }

            setNodes((nds) => nds.concat(newNode))
        },
        [reactFlowInstance, setNodes, newNodeType]
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
                colorMode={isDarkModeOn ? 'dark' : 'light'}
            >
                <Background />
                <Controls />

                {selectedNode ? (
                    <NodeDetails
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
