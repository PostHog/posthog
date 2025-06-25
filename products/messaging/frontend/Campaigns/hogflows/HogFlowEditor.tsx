import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { campaignLogic } from '../campaignLogic'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { REACT_FLOW_NODE_TYPES } from './steps/Nodes'
import { HogFlowActionNode } from './types'
import { HogFlowEditorRightPanel } from './HogFlowEditorRightPanel'

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
    } = useActions(hogFlowEditorLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)

    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

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
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={() => setSelectedNodeId(null)}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />

                <Controls showInteractive={false} />

                <HogFlowEditorRightPanel />
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
