import '@xyflow/react/dist/style.css'

import { LemonButton } from '@posthog/lemon-ui'
import {
    applyEdgeChanges,
    applyNodeChanges,
    Background,
    Controls,
    Edge,
    Node,
    ReactFlow,
    useEdgesState,
    useNodesState,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { messageCampaignLogic } from './messageCampaignLogic'

// Initial node setup - just one starting node
const initialNodes: Node[] = [
    {
        id: 'start-node',
        type: 'default',
        data: { label: 'Trigger' },
        position: { x: 250, y: 100 },
    },
]

// Initial edges setup - empty array
const initialEdges: Edge[] = []

// Node types available for adding to the flow
const NODE_TYPES = [
    { id: 'message', label: 'Message' },
    { id: 'condition', label: 'Condition' },
    { id: 'delay', label: 'Delay' },
    { id: 'exit', label: 'Exit' },
]

export function MessageCampaign(): JSX.Element {
    // Using a destructuring pattern without variable to satisfy linter
    useValues(messageCampaignLogic)
    const [nodes, setNodes] = useNodesState(initialNodes)
    const [edges, setEdges] = useEdgesState(initialEdges)
    const [nodeName, setNodeName] = useState('')
    const [selectedType, setSelectedType] = useState(NODE_TYPES[0].id)
    const [selectedNode, setSelectedNode] = useState<Node | null>(null)

    const onNodesChange = useCallback(
        (changes) => {
            setNodes((nds) => applyNodeChanges(changes, nds))
        },
        [setNodes]
    )

    const onEdgesChange = useCallback(
        (changes) => {
            setEdges((eds) => applyEdgeChanges(changes, eds))
        },
        [setEdges]
    )

    const addNode = useCallback(() => {
        if (!nodeName.trim() || !selectedNode) {
            return
        }

        // Create a unique ID for the new node
        const newNodeId = `${selectedType}-${Date.now()}`

        // Position new node below the selected node
        const newNode: Node = {
            id: newNodeId,
            type: 'default',
            data: { label: nodeName },
            position: {
                x: selectedNode.position.x,
                y: selectedNode.position.y + 100, // Position 100px below selected node
            },
        }

        // Create an edge from the selected node to the new node
        const newEdge: Edge = {
            id: `edge-${selectedNode.id}-${newNodeId}`,
            source: selectedNode.id,
            target: newNodeId,
            type: 'default',
        }

        setNodes((nds) => [...nds, newNode])
        setEdges((eds) => [...eds, newEdge])
        setNodeName('')
    }, [nodeName, selectedNode, selectedType, setNodes, setEdges])

    const onNodeClick = useCallback((_, node) => {
        setSelectedNode(node)
    }, [])

    return (
        <div className="flex flex-col space-y-4">
            <div className="flex h-[calc(100vh-300px)]">
                <div className="w-1/4 border-r p-4 space-y-4 bg-bg-light">
                    <h3 className="font-semibold text-lg">Add Node</h3>

                    <div className="space-y-2">
                        <label className="block text-sm">Node Type</label>
                        <select
                            className="border rounded p-2 w-full"
                            value={selectedType}
                            onChange={(e) => setSelectedType(e.target.value)}
                        >
                            {NODE_TYPES.map((type) => (
                                <option key={type.id} value={type.id}>
                                    {type.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="block text-sm">Node Name</label>
                        <input
                            type="text"
                            className="border rounded p-2 w-full"
                            value={nodeName}
                            onChange={(e) => setNodeName(e.target.value)}
                            placeholder="Enter node name"
                        />
                    </div>

                    <LemonButton type="primary" onClick={addNode} disabled={!nodeName.trim() || !selectedNode}>
                        Add step
                    </LemonButton>
                </div>

                <div className="w-3/4 border rounded">
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onNodeClick={onNodeClick}
                        fitView
                    >
                        <Background />
                        <Controls />
                    </ReactFlow>
                </div>
            </div>

            <div className="border rounded p-4">
                <h3 className="font-semibold text-lg mb-2">Flow JSON</h3>
                <div className="bg-bg-light rounded p-4 overflow-auto max-h-60">
                    <pre className="text-sm">{JSON.stringify({ nodes, edges }, null, 2)}</pre>
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: MessageCampaign,
    logic: messageCampaignLogic,
}
