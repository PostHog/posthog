import '@xyflow/react/dist/style.css'

import { IconPlus } from '@posthog/icons'
import {
    addEdge,
    Background,
    Controls,
    Edge,
    MiniMap,
    Node,
    ReactFlow,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
    useReactFlow,
} from '@xyflow/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { WorkflowEdge, WorkflowNode } from './types'

// Initial node setup - just one starting node
const initialNodes: Node[] = [
    {
        id: 'trigger-node',
        type: 'trigger',
        data: { label: 'Trigger' },
        position: { x: 250, y: 100 },
    },
    {
        id: 'exit-node',
        type: 'exit',
        data: { label: 'Exit' },
        position: { x: 250, y: 300 },
    },
]

// Initial edges setup - empty array
const initialEdges: Edge[] = [{ id: 'start-node-exit-node', source: 'start-node', target: 'exit-node' }]

// Node types available for adding to the flow
const NODE_TYPES = [
    { type: 'message', label: 'Message' },
    { type: 'condition', label: 'Condition' },
    { type: 'delay', label: 'Delay' },
    { type: 'exit', label: 'Exit' },
]
type NodeType = (typeof NODE_TYPES)[number]['type']

const REACT_FLOW_NODE_TYPES = {
    addIcon: AddIconNode,
    trigger: TriggerNode,
    message: MessageNode,
    condition: ConditionNode,
    delay: DelayNode,
    exit: ExitNode,
}

type WorkflowEditorProps = {
    setFlowData: ({ nodes, edges }: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }) => void
}

function TriggerNode(): JSX.Element {
    return (
        <div className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors">Trigger</div>
    )
}

function MessageNode(): JSX.Element {
    return (
        <div className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors">Message</div>
    )
}

function ConditionNode(): JSX.Element {
    return (
        <div className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors">Condition</div>
    )
}

function DelayNode(): JSX.Element {
    return <div className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors">Delay</div>
}

function ExitNode(): JSX.Element {
    return <div className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors">Exit</div>
}

function AddIconNode(): JSX.Element {
    return <IconPlus />
}

// Draggable node component
function ToolbarNode({
    type,
    label,
    setNewNodeType,
}: {
    type: string
    label: string
    setNewNodeType: (nodeType: NodeType) => void
}): JSX.Element {
    const onDragStart = (event: React.DragEvent): void => {
        setNewNodeType(type)
        event.dataTransfer.setData('application/reactflow', type)
        event.dataTransfer.effectAllowed = 'move'
    }

    return (
        <div
            className="bg-white border rounded p-2 mb-2 cursor-grab hover:bg-gray-50 transition-colors"
            draggable
            onDragStart={onDragStart}
        >
            {label}
        </div>
    )
}

function Toolbar({ setNewNodeType }: { setNewNodeType: (nodeType: NodeType) => void }): JSX.Element {
    return (
        <div className="absolute right-4 top-4 bg-white rounded-md shadow-md p-4 z-10 w-[200px]">
            <h3 className="text-sm font-semibold mb-2">Drag to add nodes</h3>
            <div className="space-y-1">
                {NODE_TYPES.map((type) => (
                    <ToolbarNode key={type.type} type={type.type} label={type.label} setNewNodeType={setNewNodeType} />
                ))}
            </div>
        </div>
    )
}

// Inner component that encapsulates React Flow
function WorkflowEditorContent({ setFlowData }: WorkflowEditorProps): JSX.Element {
    const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()
    const [newNodeType, setNewNodeType] = useState<NodeType>()

    useEffect(() => {
        setFlowData({ nodes, edges } as { nodes: WorkflowNode[]; edges: WorkflowEdge[] })
    }, [nodes, edges, setFlowData])

    const onConnect = useCallback((params) => setEdges((eds) => addEdge(params, eds)), [])

    const onDragOver = useCallback((event) => {
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
    }, [])

    const onDrop = useCallback(
        (event) => {
            event.preventDefault()

            const position = reactFlowInstance.screenToFlowPosition({
                x: event.clientX - 32,
                y: event.clientY - 32,
            })
            const newNode: Node = {
                id: `${newNodeType}_${Date.now()}`,
                type: newNodeType,
                position,
                data: {},
            }

            setNodes((nds) => nds.concat(newNode))
        },
        [reactFlowInstance, setNodes, newNodeType]
    )

    return (
        <div ref={reactFlowWrapper} className="h-full w-full">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDragOver={onDragOver}
                onDrop={onDrop}
                fitView
                nodeTypes={REACT_FLOW_NODE_TYPES}
            >
                <Background />
                <MiniMap />
                <Controls />

                <Toolbar setNewNodeType={setNewNodeType} />
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
