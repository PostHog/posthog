import { Background, BackgroundVariant, EdgeTypes, NodeTypes, Panel, ReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { KeyboardEvent, useMemo, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { CommandBar } from './CommandBar'
import { PathChip } from './PathChip'
import { PathFrame } from './PathFrame'
import { PathTrail } from './PathTrail'
import { PlacementHint } from './PlacementHint'
import { TileCanvasControls } from './TileCanvasControls'
import { TileCanvasLayoutError } from './TileCanvasLayoutError'
import { tileCanvasLogic } from './tileCanvasLogic'
import { TileCanvasMeasureLayer } from './TileCanvasMeasureLayer'
import { CANVAS_MIN_ZOOM, hasStepMenu } from './tileCanvasModel'
import { buildCanvasEdges, buildCanvasNodes, keepUnchangedNodes, TileCanvasNode, TileEdgeType } from './tileCanvasNodes'
import { TileCanvasPanel } from './TileCanvasPanel'
import { TileEdge } from './TileEdge'
import { TileFlowNode } from './TileFlowNode'
import { useCanvasViewport } from './useCanvasViewport'

const NODE_TYPES = { tile: TileFlowNode, frame: PathFrame, chip: PathChip } as NodeTypes
const EDGE_TYPES = { tile: TileEdge } as EdgeTypes
const MAX_ZOOM = 1.5

type TileKeyCommand = 'activate' | 'menu'

function tileKeyCommand(event: KeyboardEvent<HTMLElement>): TileKeyCommand | null {
    if (event.key === 'Enter' || event.key === ' ') {
        return 'activate'
    }
    return event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10') ? 'menu' : null
}

/** React Flow focuses its own node wrapper, which carries the node id. */
function focusedTileId(event: KeyboardEvent<HTMLElement>): string | undefined {
    const target = event.target as HTMLElement
    return target.classList.contains('react-flow__node-tile') ? target.dataset.id : undefined
}

export function TileCanvasContent(): JSX.Element {
    const wrapperRef = useRef<HTMLDivElement>(null)
    const { isDarkModeOn } = useValues(themeLogic)
    const {
        drawnGraph,
        frameSpecs,
        layout,
        motion,
        isPanelOpen,
        commandPaletteQuery,
        layoutError,
        workflow,
        pathGroups,
        measuredSizes,
        selectedStepId,
        stepMenuActionId,
        countOf,
        templateNameOf,
    } = useValues(tileCanvasLogic)
    const { activateNode, openStepMenu, handlePaneClick } = useActions(tileCanvasLogic)
    useCanvasViewport(wrapperRef)

    const previousNodes = useRef<TileCanvasNode[]>([])
    const nodes = useMemo(() => {
        const state = {
            workflow,
            groups: pathGroups,
            motion,
            sizes: measuredSizes,
            selectedStepId,
            menuStepId: stepMenuActionId,
            countOf,
            templateNameOf,
        }
        previousNodes.current = keepUnchangedNodes(
            previousNodes.current,
            buildCanvasNodes(layout, frameSpecs, drawnGraph, state)
        )
        return previousNodes.current
    }, [
        layout,
        frameSpecs,
        drawnGraph,
        workflow,
        pathGroups,
        motion,
        measuredSizes,
        selectedStepId,
        stepMenuActionId,
        countOf,
        templateNameOf,
    ])
    const edges = useMemo(() => buildCanvasEdges(drawnGraph, layout), [drawnGraph, layout])

    const hasMenu = (nodeId: string): boolean =>
        drawnGraph.nodes.some((node) => node.id === nodeId && node.kind === 'step' && hasStepMenu(node.action))

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        const nodeId = focusedTileId(event)
        const command = nodeId ? tileKeyCommand(event) : null
        if (!nodeId || !command) {
            return
        }
        event.preventDefault()
        if (command === 'activate') {
            activateNode(nodeId)
        } else if (hasMenu(nodeId)) {
            openStepMenu(nodeId, true)
        }
    }

    return (
        <div
            className={cn(
                'TileCanvas relative flex min-h-0 min-w-0 flex-1 overflow-hidden @max-[48rem]/workflow-editor:flex-col @max-[48rem]/workflow-editor:overflow-y-auto',
                motion && 'TileCanvas--moving'
            )}
            data-attr="workflow-editor"
        >
            <TileCanvasMeasureLayer />
            <div
                ref={wrapperRef}
                onKeyDown={onKeyDown}
                className="TileCanvas__flow @container/tile-canvas relative flex min-h-0 min-w-0 grow @max-[48rem]/workflow-editor:min-h-48"
            >
                <ReactFlow<TileCanvasNode, TileEdgeType>
                    className="grow"
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={NODE_TYPES}
                    edgeTypes={EDGE_TYPES}
                    minZoom={CANVAS_MIN_ZOOM}
                    maxZoom={MAX_ZOOM}
                    panOnScroll
                    zoomOnScroll={false}
                    zoomActivationKeyCode={['Meta', 'Control']}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    edgesFocusable={false}
                    colorMode={isDarkModeOn ? 'dark' : 'light'}
                    onNodeClick={(_, node) => activateNode(node.id)}
                    onPaneClick={handlePaneClick}
                    proOptions={{ hideAttribution: true }}
                >
                    <Background gap={36} variant={BackgroundVariant.Dots} />
                    <Panel position="top-left" className="!m-2 max-w-[calc(100%-1rem)]">
                        <PathTrail />
                    </Panel>
                    {/* A narrow editor stacks the panel under the canvas, which leaves no room for the bar over it. */}
                    <Panel
                        position="bottom-center"
                        className={cn('!mb-5', isPanelOpen && '@max-[48rem]/workflow-editor:hidden')}
                    >
                        <div className="flex flex-col items-center gap-2">
                            {commandPaletteQuery === null && <PlacementHint />}
                            <CommandBar />
                        </div>
                    </Panel>
                    <TileCanvasControls />
                </ReactFlow>
                {layoutError && <TileCanvasLayoutError message={layoutError} />}
            </div>
            {isPanelOpen && <TileCanvasPanel />}
        </div>
    )
}
