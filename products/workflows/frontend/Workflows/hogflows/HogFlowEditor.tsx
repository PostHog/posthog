import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    EdgeTypes,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { workflowLogic } from '../workflowLogic'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlowEditorPanel } from './panel/HogFlowEditorPanel'
import { REACT_FLOW_NODE_TYPES } from './steps/Nodes'
import { REACT_FLOW_EDGE_TYPES } from './steps/SmartEdge'
import { HogFlowActionNode } from './types'

// Inner component that encapsulates React Flow
function HogFlowEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges, dropzoneNodes } = useValues(hogFlowEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        onDragStart,
        onDragOver,
        onDrop,
        setReactFlowWrapper,
    } = useActions(hogFlowEditorLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    return (
        <div ref={reactFlowWrapper} className="w-full h-full">
            <ReactFlow<HogFlowActionNode, Edge>
                fitView
                nodes={[...nodes, ...(dropzoneNodes as unknown as HogFlowActionNode[])]}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                edgeTypes={REACT_FLOW_EDGE_TYPES as EdgeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={() => setSelectedNodeId(null)}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />

                <Controls showInteractive={false} />

                <HogFlowEditorPanel />
            </ReactFlow>
        </div>
    )
}

export function HogFlowEditor(): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    return (
        <ReactFlowProvider>
            <BindLogic logic={hogFlowEditorLogic} props={logicProps}>
                <HogFlowEditorContent />
            </BindLogic>
        </ReactFlowProvider>
    )
}
