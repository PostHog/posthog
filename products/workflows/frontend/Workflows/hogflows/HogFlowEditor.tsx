import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    EdgeTypes,
    NodeTypes,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconInfo } from '@posthog/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { workflowLogic } from '../workflowLogic'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlowEditorPanel } from './panel/HogFlowEditorPanel'
import { REACT_FLOW_EDGE_TYPES } from './react_flow_utils/SmartEdge'
import { REACT_FLOW_NODE_TYPES } from './steps/Nodes'
import { HogFlowActionEdge, HogFlowActionNode } from './types'

// Inner component that encapsulates React Flow
function HogFlowEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges, dropzoneNodes, isMovingNode, isCopyingNode } = useValues(hogFlowEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        showDropzones,
        onDragOver,
        onDrop,
        setReactFlowWrapper,
        handlePaneClick,
    } = useActions(hogFlowEditorLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    // ReactFlow diffs its nodes prop by reference: an inline spread would hand it a fresh array
    // every render, making every render look like a graph change.
    const nodesWithDropzones = useMemo(
        () => [...nodes, ...(dropzoneNodes as unknown as HogFlowActionNode[])],
        [nodes, dropzoneNodes]
    )

    return (
        <div ref={reactFlowWrapper} className="flex flex-col grow w-full" data-attr="workflow-editor">
            <ReactFlow<HogFlowActionNode, HogFlowActionEdge>
                className="grow"
                fitView
                nodes={nodesWithDropzones}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={showDropzones}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                edgeTypes={REACT_FLOW_EDGE_TYPES as EdgeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={handlePaneClick}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />

                {(isMovingNode || isCopyingNode) && (
                    <Panel position="bottom-left">
                        {/* Offset right of the zoom controls so the hint sits beside them */}
                        <div className="flex items-center gap-1.5 ml-12 px-3 py-1.5 rounded border shadow-sm bg-surface-primary text-sm">
                            <IconInfo className="text-base text-muted shrink-0" />
                            <span>Click a highlighted spot to {isMovingNode ? 'move' : 'copy'} this step</span>
                            <span className="text-muted">· press Esc to cancel</span>
                        </div>
                    </Panel>
                )}

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
