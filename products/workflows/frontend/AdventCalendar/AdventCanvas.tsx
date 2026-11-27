import '@xyflow/react/dist/style.css'

import { Edge, Node, NodeTypes, ReactFlow, Viewport } from '@xyflow/react'
import { useMemo } from 'react'

import { AdventDoorNode, AdventDoorNodeType } from './AdventDoorNode'
import { ADVENT_TRIGGER_ID, AdventGraph, AdventLink } from './adventGraph'
import { AdventPalette, adventPalette } from './adventPalette'
import { AdventTriggerNode } from './AdventTriggerNode'

const NODE_TYPES = { door: AdventDoorNode, trigger: AdventTriggerNode } as NodeTypes

function edgeOf(link: AdventLink, palette: AdventPalette): Edge {
    return {
        id: link.id,
        source: link.from,
        target: link.to,
        sourceHandle: link.from === ADVENT_TRIGGER_ID ? 'out-right' : `out-${link.fromSide}`,
        targetHandle: `in-${link.toSide}`,
        type: 'default',
        style: {
            stroke: link.walked ? palette.red : palette.ink,
            strokeWidth: link.walked ? 3 : 2,
            opacity: link.walked ? 1 : 0.5,
        },
    }
}

export interface AdventCanvasProps {
    graph: AdventGraph
    viewport: Viewport
    today: number
    selectedDoorId: string | null
    openingDoorId: string | null
    onActivateDoor: (doorId: string) => void
    onEnterDoor: (doorId: string) => void
    onLeaveDoor: () => void
    onPaneClick: () => void
}

export function AdventCanvas({
    graph,
    viewport,
    today,
    selectedDoorId,
    openingDoorId,
    onActivateDoor,
    onEnterDoor,
    onLeaveDoor,
    onPaneClick,
}: AdventCanvasProps): JSX.Element {
    const nodes = useMemo<Node[]>(
        () => [
            { id: ADVENT_TRIGGER_ID, type: 'trigger', position: graph.trigger, data: {}, selectable: false },
            ...graph.doors.map(
                (door): AdventDoorNodeType => ({
                    id: door.id,
                    type: 'door',
                    position: { x: door.x, y: door.y },
                    data: {
                        door,
                        isSelected: door.id === selectedDoorId,
                        isToday: door.day === today,
                        isOpening: door.id === openingDoorId,
                    },
                    selectable: false,
                })
            ),
        ],
        [graph, selectedDoorId, openingDoorId, today]
    )

    const edges = useMemo<Edge[]>(() => graph.links.map((link) => edgeOf(link, adventPalette())), [graph])

    return (
        <ReactFlow
            className="!bg-transparent"
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            viewport={viewport}
            minZoom={0.1}
            maxZoom={4}
            panOnDrag={false}
            panOnScroll={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            zoomOnDoubleClick={false}
            preventScrolling={false}
            nodesDraggable={false}
            nodesConnectable={false}
            nodesFocusable={false}
            edgesFocusable={false}
            onNodeClick={(_, node) => onActivateDoor(node.id)}
            onNodeMouseEnter={(_, node) => {
                if (node.id !== ADVENT_TRIGGER_ID) {
                    onEnterDoor(node.id)
                }
            }}
            onNodeMouseLeave={onLeaveDoor}
            onPaneClick={onPaneClick}
            proOptions={{ hideAttribution: true }}
        />
    )
}
