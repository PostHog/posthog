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
    useNodesInitialized,
    useReactFlow,
} from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'

import { IconInfo } from '@posthog/icons'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { workflowLogic } from '../workflowLogic'
import { HogFlowBranchSelectionProvider } from './HogFlowBranchSelection'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlowEditorPanel } from './panel/HogFlowEditorPanel'
import { LOW_DETAIL_ZOOM, MAX_ZOOM, MIN_ZOOM } from './react_flow_utils/constants'
import { REACT_FLOW_EDGE_TYPES } from './react_flow_utils/SmartEdge'
import { REACT_FLOW_NODE_TYPES } from './steps/Nodes'
import { HogFlowTreeEditor } from './tree/HogFlowTreeEditor'
import { HogFlowActionEdge, HogFlowActionNode } from './types'

function HogFlowGraphEditor(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges, dropzoneNodes, isMovingNode, isCopyingNode, isZoomedOutFar } = useValues(hogFlowEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        onDragOver,
        onDrop,
        setReactFlowWrapper,
        handlePaneClick,
        setIsZoomedOutFar,
        fitView,
    } = useActions(hogFlowEditorLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()
    const nodesInitialized = useNodesInitialized()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    useEffect(() => {
        if (!nodesInitialized || !reactFlowWrapper.current) {
            return
        }

        const observer = new ResizeObserver(() => fitView({ duration: 0 }))
        observer.observe(reactFlowWrapper.current)
        return () => observer.disconnect()
    }, [fitView, nodesInitialized])

    // ReactFlow diffs its nodes prop by reference: an inline spread would hand it a fresh array
    // every render, making every render look like a graph change.
    const nodesWithDropzones = useMemo(
        () => [...nodes, ...(dropzoneNodes as unknown as HogFlowActionNode[])],
        [nodes, dropzoneNodes]
    )

    return (
        <div
            className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden @max-[32rem]/workflow-editor:flex-col @max-[32rem]/workflow-editor:overflow-y-auto"
            data-attr="workflow-editor"
        >
            <div
                ref={reactFlowWrapper}
                className="flex min-h-0 min-w-0 grow @max-[32rem]/workflow-editor:min-h-80 @max-[32rem]/workflow-editor:shrink-0"
            >
                <ReactFlow<HogFlowActionNode, HogFlowActionEdge>
                    className="grow"
                    fitView
                    minZoom={MIN_ZOOM}
                    maxZoom={MAX_ZOOM}
                    // Only dispatched when the detail tier flips, so panning and zooming don't put a
                    // Redux action on every animation frame.
                    onMove={(_, viewport) => {
                        const zoomedOutFar = viewport.zoom < LOW_DETAIL_ZOOM
                        if (zoomedOutFar !== isZoomedOutFar) {
                            setIsZoomedOutFar(zoomedOutFar)
                        }
                    }}
                    nodes={nodesWithDropzones}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodesDelete={onNodesDelete}
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
                            <div className="flex flex-wrap items-center gap-1.5 ml-12 px-3 py-1.5 rounded border shadow-sm bg-surface-primary text-sm">
                                <IconInfo className="text-base text-muted shrink-0" />
                                <span>Click a highlighted spot to {isMovingNode ? 'move' : 'copy'} this step</span>
                                <span className="text-muted">· press Esc to cancel</span>
                            </div>
                        </Panel>
                    )}

                    <Controls showInteractive={false} />
                </ReactFlow>
            </div>

            <HogFlowEditorPanel />
        </div>
    )
}

function HogFlowTreeEditorContent(): JSX.Element {
    return (
        <div
            className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden @max-[32rem]/workflow-editor:flex-col @max-[32rem]/workflow-editor:overflow-y-auto"
            data-attr="workflow-editor"
        >
            <HogFlowTreeEditor />
            <HogFlowEditorPanel layout="panel" />
        </div>
    )
}

// Match the 32rem and 48rem container-query breakpoints in the editor classes, at a 16px root font size
function getEditorLayout(width: number): 'stacked' | 'compact' | 'wide' {
    return width < 512 ? 'stacked' : width < 768 ? 'compact' : 'wide'
}

export function HogFlowEditor({ isTreeView }: { isTreeView: boolean }): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const width = containerRef.current?.getBoundingClientRect().width ?? 0
        posthog.capture('workflows editor opened', {
            view: isTreeView ? 'list' : 'graph',
            layout: getEditorLayout(width),
            editor_width: Math.round(width),
            side_panel_open: sidePanelOpen,
        })
        // Report the layout once per view, not on every side panel toggle
        // oxlint-disable-next-line exhaustive-deps
    }, [isTreeView])

    return (
        <BindLogic logic={hogFlowEditorLogic} props={logicProps}>
            <HogFlowBranchSelectionProvider>
                <div ref={containerRef} className="@container/workflow-editor flex min-h-0 min-w-0 flex-1">
                    {isTreeView ? (
                        <ReactFlowProvider>
                            <HogFlowTreeEditorContent />
                        </ReactFlowProvider>
                    ) : (
                        <ReactFlowProvider>
                            <HogFlowGraphEditor />
                        </ReactFlowProvider>
                    )}
                </div>
            </HogFlowBranchSelectionProvider>
        </BindLogic>
    )
}
