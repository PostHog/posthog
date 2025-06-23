import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    Node,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { campaignLogic } from '../campaignLogic'
import { NodeDetailsPanel } from './actions/NodeDetailsPanel'
import { REACT_FLOW_NODE_TYPES } from './actions/Nodes'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlowEditorToolbar } from './HogFlowEditorToolbar'
import type { HogFlowAction } from './types'

// Inner component that encapsulates React Flow
function HogFlowEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges, selectedNode, dropzoneNodes } = useValues(hogFlowEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNode,
        setReactFlowInstance,
        onNodesDelete,
        onDragStart,
        onDragOver,
        onDrop,
    } = useActions(hogFlowEditorLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)

    const { fitView } = useReactFlow() // TODO: Move this to the logic too
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    // Center content whenever nodes positions change
    useEffect(() => {
        void fitView()
    }, [fitView, nodes])

    // const onDragStart = useCallback(() => {
    //     setNodes(HogFlowActionManager.addDropzoneNodes(nodes, edges))
    // }, [nodes, edges, setNodes])

    // const onDragOver = useCallback(
    //     (event: React.DragEvent) => {
    //         event.preventDefault()
    //         event.dataTransfer.dropEffect = 'move'

    //         setNodes((nds) =>
    //             HogFlowActionManager.highlightDropzoneNodes(nds, event, screenToFlowPosition, getIntersectingNodes)
    //         )
    //     },
    //     [screenToFlowPosition, getIntersectingNodes, setNodes]
    // )

    // const onDrop = useCallback(
    //     (event: React.DragEvent) => {
    //         event.preventDefault()

    //         const intersectingDropzone = HogFlowActionManager.findIntersectingDropzone(
    //             event,
    //             screenToFlowPosition,
    //             getIntersectingNodes
    //         )
    //         if (!toolbarNodeUsed || !intersectingDropzone) {
    //             // No changes, just hide dropzones
    //             setNodes((nds) => HogFlowActionManager.removeDropzoneNodes(nds))
    //             return
    //         }

    //         // Create the new node in the position of the dropzone using the manager
    //         const updatedActions = HogFlowActionManager.insertNodeIntoDropzone(
    //             hogFlow.actions,
    //             toolbarNodeUsed,
    //             intersectingDropzone
    //         )
    //         onChange({ actions: updatedActions })
    //     },
    //     [screenToFlowPosition, getIntersectingNodes, toolbarNodeUsed, hogFlow.actions, onChange, setNodes]
    // )

    return (
        <div ref={reactFlowWrapper} className="w-full h-full">
            <ReactFlow<Node<HogFlowAction>, Edge>
                fitView
                nodes={[...nodes, ...dropzoneNodes]}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onNodeClick={(_, node) => node.selectable && setSelectedNode(node)}
                onDrop={onDrop}
                nodeTypes={REACT_FLOW_NODE_TYPES}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
            >
                <Controls showInteractive={false} />

                <Background gap={36} variant={BackgroundVariant.Dots} />

                <HogFlowEditorToolbar />

                {selectedNode && (
                    <NodeDetailsPanel
                        node={selectedNode}
                        // onChange={(node) => setNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)))}
                        // onDelete={(node) => {
                        //     void deleteElements({ nodes: [node] })
                        // }}
                        // onClose={() => setSelectedNode(undefined)}
                    />
                )}
            </ReactFlow>
        </div>
    )
}

export function HogFlowEditor(): JSX.Element {
    const { logicProps } = useValues(campaignLogic)
    return (
        <ReactFlowProvider>
            <BindLogic logic={hogFlowEditorLogic} props={logicProps}>
                <HogFlowEditorContent />
            </BindLogic>
        </ReactFlowProvider>
    )
}
