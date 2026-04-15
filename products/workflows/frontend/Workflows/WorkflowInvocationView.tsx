import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    EdgeTypes,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { HogFlowEditorPanelInvocation } from './hogflows/panel/HogFlowEditorPanelInvocation'
import { REACT_FLOW_EDGE_TYPES } from './hogflows/react_flow_utils/SmartEdge'
import { REACT_FLOW_NODE_TYPES } from './hogflows/steps/Nodes'
import { HogFlowActionEdge, HogFlowActionNode } from './hogflows/types'
import { invocationViewLogic, InvocationViewLogicProps } from './invocationViewLogic'
import { workflowLogic } from './workflowLogic'

function InvocationCanvas({ instanceId }: { instanceId: string }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { nodes, edges, dropzoneNodes, mode } = useValues(hogFlowEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
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

    // Hide dropzones in invocation mode
    const displayNodes =
        mode === 'invocation' ? nodes : [...nodes, ...(dropzoneNodes as unknown as HogFlowActionNode[])]

    return (
        <div ref={reactFlowWrapper} className="flex flex-col grow w-full" data-attr="workflow-invocation-canvas">
            <ReactFlow<HogFlowActionNode, HogFlowActionEdge>
                className="grow"
                fitView
                nodes={displayNodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                edgeTypes={REACT_FLOW_EDGE_TYPES as EdgeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={handlePaneClick}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />
                <Controls showInteractive={false} />
                <InvocationPanel instanceId={instanceId} />
            </ReactFlow>
        </div>
    )
}

function InvocationPanel({ instanceId }: { instanceId: string }): JSX.Element {
    const { selectedNode } = useValues(hogFlowEditorLogic)

    return (
        <div
            className="absolute flex flex-col m-0 p-2 overflow-hidden max-h-full right-0 justify-end"
            style={{ width: '37rem' }}
        >
            <div
                className="relative flex flex-col rounded-md overflow-hidden bg-surface-primary max-h-full z-10"
                style={{
                    border: '1px solid var(--border)',
                    boxShadow: '0 3px 0 var(--border)',
                }}
            >
                <div className="flex gap-2 border-b items-center px-2 py-1.5">
                    <span className="font-semibold text-sm">
                        {selectedNode ? selectedNode.data.name : 'Invocation logs'}
                    </span>
                </div>
                <HogFlowEditorPanelInvocation instanceId={instanceId} />
            </div>
        </div>
    )
}

function InvocationHeader({ workflowId, instanceId }: { workflowId: string; instanceId: string }): JSX.Element {
    const invocationProps: InvocationViewLogicProps = { workflowId, instanceId }
    const { personInfo, isCompleted, isErrored, logsLoading } = useValues(invocationViewLogic(invocationProps))

    const statusTag = isErrored ? (
        <LemonTag type="danger">Errored</LemonTag>
    ) : isCompleted ? (
        <LemonTag type="success">Completed</LemonTag>
    ) : logsLoading ? (
        <LemonTag type="muted">Loading</LemonTag>
    ) : (
        <LemonTag type="highlight">In progress</LemonTag>
    )

    return (
        <div className="flex items-center gap-2 px-4 py-2 border-b bg-surface-primary">
            <LemonButton type="secondary" size="small" icon={<IconArrowLeft />} to={urls.workflow(workflowId, 'logs')}>
                Back to invocations
            </LemonButton>
            <div className="flex-1" />
            {personInfo && (
                <PersonDisplay person={{ id: personInfo.id }} displayName={personInfo.name} withIcon="sm" inline />
            )}
            {statusTag}
        </div>
    )
}

function InvocationViewInner({ workflowId, instanceId }: { workflowId: string; instanceId: string }): JSX.Element {
    const invocationProps: InvocationViewLogicProps = { workflowId, instanceId }
    const { nodeStatuses, traversedEdges, currentNodeId, logsLoading, logs } = useValues(
        invocationViewLogic(invocationProps)
    )
    const { setMode, setInvocationState, clearInvocationState } = useActions(hogFlowEditorLogic)

    // Set invocation mode and sync state
    useEffect(() => {
        setMode('invocation')
        return () => {
            clearInvocationState()
            setMode('build')
        }
    }, [setMode, clearInvocationState])

    useEffect(() => {
        if (logs.length > 0) {
            setInvocationState(nodeStatuses, traversedEdges, currentNodeId)
        }
    }, [nodeStatuses, traversedEdges, currentNodeId, logs.length, setInvocationState])

    if (logsLoading && logs.length === 0) {
        return (
            <div className="flex justify-center items-center flex-1">
                <Spinner size="large" />
            </div>
        )
    }

    return <InvocationCanvas instanceId={instanceId} />
}

export function WorkflowInvocationView({
    workflowId,
    instanceId,
}: {
    workflowId: string
    instanceId: string
}): JSX.Element {
    const { logicProps } = useValues(workflowLogic)

    return (
        <div className="flex flex-col grow">
            <InvocationHeader workflowId={workflowId} instanceId={instanceId} />
            <ReactFlowProvider>
                <BindLogic logic={hogFlowEditorLogic} props={logicProps}>
                    <InvocationViewInner workflowId={workflowId} instanceId={instanceId} />
                </BindLogic>
            </ReactFlowProvider>
        </div>
    )
}
