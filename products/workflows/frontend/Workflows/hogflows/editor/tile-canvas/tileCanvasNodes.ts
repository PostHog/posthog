import type { Edge, Node } from '@xyflow/react'

import type { HogFlow } from '../../types'
import { Box, CanvasLayout, frameChipWidth, frameEntryX, NodeSize, PathFrameSpec, RoutedEdge } from './tileCanvasLayout'
import type { StepCountOf, TemplateNameOf } from './tileCanvasLogic'
import {
    CanvasMotion,
    frameMotion,
    nodeMotion,
    NodeMotion,
    PathGroup,
    VisibleEdge,
    VisibleGraph,
    VisibleNode,
} from './tileCanvasModel'

export interface TileNodeData extends Record<string, unknown> {
    node: VisibleNode
    workflow: HogFlow
    motion?: NodeMotion
    count?: number
    selected: boolean
    menuOpen: boolean
    countOf: StepCountOf
    templateNameOf: TemplateNameOf
}

export interface PathNodeData extends Record<string, unknown> {
    group: PathGroup
    motion?: NodeMotion
}

export type TileFlowNodeType = Node<TileNodeData, 'tile'>
export type PathFrameNodeType = Node<PathNodeData, 'frame'>
export type PathChipNodeType = Node<PathNodeData, 'chip'>
export type TileCanvasNode = TileFlowNodeType | PathFrameNodeType | PathChipNodeType

export type TileEdgeType = Edge<{ edge: VisibleEdge; routed?: RoutedEdge }, 'tile'>

/** What every node shows besides its place: the parts of the canvas state a node needs to draw itself. */
export interface CanvasNodeState {
    workflow: HogFlow
    groups: PathGroup[]
    motion: CanvasMotion | null
    sizes: Record<string, NodeSize> | null
    selectedStepId: string | null
    menuStepId: string | null
    countOf: StepCountOf
    templateNameOf: TemplateNameOf
}

const CHIP_INSET = 8
const STATIC = { selectable: false, draggable: false } as const

function frameNode(frame: PathFrameSpec, box: Box, motion: NodeMotion | undefined): TileCanvasNode {
    return {
        id: frame.id,
        type: 'frame',
        position: { x: box.x, y: box.y },
        width: box.width,
        height: box.height,
        data: { group: frame.group, motion },
        zIndex: -10 + frame.group.depth,
        ...STATIC,
    }
}

/** The chip sits where the arrow into the path crosses the frame's top edge, kept inside the frame. */
function chipNode(
    frame: PathFrameSpec,
    box: Box,
    layout: CanvasLayout,
    graph: VisibleGraph,
    motion: NodeMotion | undefined
): TileCanvasNode {
    const x = frameEntryX(frame.group, box, layout, graph.edges)
    const width = frameChipWidth(frame.group.label)
    const left = Math.min(Math.max(x - width / 2, box.x + CHIP_INSET), box.x + box.width - width - CHIP_INSET)
    return {
        id: `chip:${frame.group.id}`,
        type: 'chip',
        position: { x: left, y: box.y },
        data: { group: frame.group, motion },
        zIndex: 5,
        ...STATIC,
    }
}

function tileNode(node: VisibleNode, layout: CanvasLayout, state: CanvasNodeState): TileCanvasNode[] {
    const position = layout.positions[node.id]
    if (!position) {
        return []
    }
    const size = state.sizes?.[node.id]
    const data: TileNodeData = {
        node,
        workflow: state.workflow,
        motion: nodeMotion(state.motion, node, state.groups, size && { ...position, ...size }),
        count: node.kind === 'step' ? state.countOf(node.id) : undefined,
        selected: state.selectedStepId === node.id,
        menuOpen: state.menuStepId === node.id,
        countOf: state.countOf,
        templateNameOf: state.templateNameOf,
    }
    // React Flow hides a replaced node until it measures it again, unless the node says its size.
    const measured = size && { width: size.width, height: size.height }
    return [{ id: node.id, type: 'tile', position, data, measured, ...STATIC }]
}

const missingFrom = <Item extends { id: string }>(items: Item[], present: Item[]): Item[] => {
    const ids = new Set(present.map((item) => item.id))
    return items.filter((item) => !ids.has(item.id))
}

/**
 * Laying out the canvas takes a moment. Until the new layout lands, a stack that opens stays where the last layout put
 * it, with its arrows, so its steps can fly out of it instead of out of an empty gap. The steps and frame of a path
 * that collapses have already faded out, so they do not come back.
 */
export function withLeavingStacks(current: VisibleGraph, laidOut: VisibleGraph | null): VisibleGraph {
    const leaving = laidOut ? missingFrom(laidOut.nodes, current.nodes).filter((node) => node.kind === 'stack') : []
    if (!laidOut || !leaving.length) {
        return current
    }
    const nodes = [...current.nodes, ...leaving]
    const drawnIds = new Set(nodes.map((node) => node.id))
    const edges = missingFrom(laidOut.edges, current.edges).filter(
        (edge) => drawnIds.has(edge.source) && drawnIds.has(edge.target)
    )
    return { nodes, edges: [...current.edges, ...edges] }
}

export function buildCanvasNodes(
    layout: CanvasLayout | null,
    frameSpecs: PathFrameSpec[],
    graph: VisibleGraph,
    state: CanvasNodeState
): TileCanvasNode[] {
    if (!layout) {
        return []
    }
    const framed = frameSpecs.flatMap((frame) => {
        const box = layout.frames[frame.id]
        return box ? [{ frame, box, motion: frameMotion(state.motion, frame.group, state.groups) }] : []
    })
    return [
        ...framed.map(({ frame, box, motion }) => frameNode(frame, box, motion)),
        ...framed.map(({ frame, box, motion }) => chipNode(frame, box, layout, graph, motion)),
        ...graph.nodes.flatMap((node) => tileNode(node, layout, state)),
    ]
}

const shallowEqual = (a: Record<string, unknown>, b: Record<string, unknown>): boolean => {
    const keys = Object.keys(a)
    return keys.length === Object.keys(b).length && keys.every((key) => a[key] === b[key])
}

function isUnchanged(previous: TileCanvasNode, next: TileCanvasNode): boolean {
    return (
        previous.type === next.type &&
        previous.position.x === next.position.x &&
        previous.position.y === next.position.y &&
        previous.width === next.width &&
        previous.height === next.height &&
        previous.zIndex === next.zIndex &&
        shallowEqual(previous.data, next.data)
    )
}

/** React Flow redraws a node whose object changed, so a node that looks the same keeps its old object. */
export function keepUnchangedNodes(previous: TileCanvasNode[], next: TileCanvasNode[]): TileCanvasNode[] {
    const previousById = new Map(previous.map((node) => [node.id, node]))
    return next.map((node) => {
        const old = previousById.get(node.id)
        return old && isUnchanged(old, node) ? old : node
    })
}

export function buildCanvasEdges(graph: VisibleGraph, layout: CanvasLayout | null): TileEdgeType[] {
    return graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: 'tile',
        data: { edge, routed: layout?.edges[edge.id] },
        selectable: false,
    }))
}
