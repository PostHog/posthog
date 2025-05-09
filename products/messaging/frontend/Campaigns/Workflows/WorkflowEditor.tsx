import '@xyflow/react/dist/style.css'

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
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { IconDecisionTree, IconHourglass, IconLeave, IconSend } from 'node_modules/@posthog/icons/dist'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { REACT_FLOW_NODE_TYPES } from './Node'
import { nodeDetailsLogic } from './nodeDetailsLogic'
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

// Initial edges setup
const initialEdges: Edge[] = [{ id: 'trigger-node-exit-node', source: 'trigger-node', target: 'exit-node' }]

// Node types available for adding to the flow
const TOOLBAR_NODE_TYPES = [
    { type: 'message', label: 'Message', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Delay', icon: <IconHourglass /> },
    { type: 'exit', label: 'Exit', icon: <IconLeave /> },
]
type ToolbarNodeType = (typeof TOOLBAR_NODE_TYPES)[number]['type']

type WorkflowEditorProps = {
    setFlowData: ({ nodes, edges }: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }) => void
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
            className="bg-surface-primary border rounded p-2 mb-2 cursor-grab hover:bg-surface-secondary transition-colors"
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
        <div className="absolute right-4 top-4 bg-surface-primary rounded-md shadow-md p-4 z-10 w-[200px]">
            <h3 className="text-sm font-semibold mb-2">Drag to add nodes</h3>
            <div className="space-y-1">
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
}: {
    workflowId: string
    node: WorkflowNode
    onNodeChange: (node: WorkflowNode) => void
}): JSX.Element {
    nodeDetailsLogic({
        workflowId,
        node,
        onNodeChange,
    })

    return (
        <div className="absolute right-4 top-4 bg-white rounded-md shadow-md p-4 z-10 w-[200px]">
            <h3 className="text-sm font-semibold mb-2">Edit {node.type} node</h3>
            <Form logic={nodeDetailsLogic} formKey="node">
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="space-y-2 flex-1 min-w-100 p-3 bg-surface-primary border rounded self-start">
                        <LemonField name="name" label="Name">
                            <LemonInput />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonTextArea />
                        </LemonField>
                    </div>
                </div>
            </Form>
        </div>
    )
}

// Inner component that encapsulates React Flow
function WorkflowEditorContent({ setFlowData }: WorkflowEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()
    const [newNodeType, setNewNodeType] = useState<ToolbarNodeType>()
    const [selectedNode, setSelectedNode] = useState<Node>()

    const nodeTypes = useMemo(() => REACT_FLOW_NODE_TYPES, [])

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

            if (!newNodeType) {
                return
            }

            const position = reactFlowInstance.screenToFlowPosition({
                x: event.clientX - 32,
                y: event.clientY - 32,
            })
            const newNode: Node = {
                id: `${newNodeType}_${Date.now()}`,
                type: newNodeType,
                position,
                data: {
                    label: capitalizeFirstLetter(newNodeType),
                },
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
                onNodeClick={(_, node) => setSelectedNode(node)}
                onDrop={onDrop}
                fitView
                nodeTypes={nodeTypes}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
            >
                <Background />
                <Controls />

                <Toolbar setNewNodeType={setNewNodeType} />
                {selectedNode && (
                    <NodeDetails
                        workflowId="new"
                        node={selectedNode as WorkflowNode}
                        onNodeChange={(node) => setNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)))}
                    />
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
