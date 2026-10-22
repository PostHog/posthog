import type { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { getElk } from 'lib/elk'

import { getEdgeId } from '../../edgeId'
import { isInPathGroup, openPathFrames, PathGroup, Point, VisibleEdge, VisibleNode } from './tileCanvasModel'

export const TILE_SIZE = 64
export const EDGE_LABEL_HEIGHT = 22
const BADGE_ROOM = 10
const PORT_SPREAD = 14
const FRAME_PADDING = { top: 30, side: 16, bottom: 16 }

export interface Box {
    x: number
    y: number
    width: number
    height: number
}

export interface NodeSize {
    width: number
    height: number
    anchor?: Box
}

export interface RoutedEdge {
    points: Point[]
    label?: Point
    labelBox?: Box
}

export interface CanvasLayout {
    positions: Record<string, Point>
    edges: Record<string, RoutedEdge>
    frames: Record<string, Box>
    width: number
    height: number
}

export interface PathFrameSpec {
    id: string
    group: PathGroup
    parentId: string | null
    memberIds: string[]
    minWidth: number
}

const LABEL_MAX_CHARS = 40
/** A condition name can run to a sentence, and a label that long would set the width of its whole path. */
export const shortLabel = (text: string): string =>
    text.length <= LABEL_MAX_CHARS ? text : `${text.slice(0, LABEL_MAX_CHARS - 1).trimEnd()}…`
export const edgeLabelWidth = (text: string): number => Math.ceil(shortLabel(text).length * 6.6) + 20
/** The chip also holds the Collapse control after the name. */
export const frameChipWidth = (label: string): number => Math.ceil(shortLabel(label).length * 7.6) + 136

export const frameId = (group: PathGroup): string => `frame:${group.id}`

export function pathFrameSpecs(
    groups: PathGroup[],
    openGroupIds: readonly string[],
    nodes: VisibleNode[]
): PathFrameSpec[] {
    return openPathFrames(groups, openGroupIds).map((group) => ({
        id: frameId(group),
        group,
        parentId: group.parentId ? `frame:${group.parentId}` : null,
        memberIds: nodes.filter((node) => isInPathGroup(group, node)).map((node) => node.id),
        minWidth: frameChipWidth(group.label) + 32,
    }))
}

/** Where the arrow into a laid-out tile or stack meets it. */
export function tileEntry(position: Point, size: NodeSize): Point {
    return { x: position.x + (size.anchor ? size.anchor.x : size.width / 2), y: position.y }
}

function tilePorts(size: NodeSize, count: number): { in: Point; out: Point[] } {
    const centerX = tileEntry({ x: 0, y: 0 }, size).x
    return {
        in: { x: centerX, y: 0 },
        out: Array.from({ length: count }, (_, index) => ({
            x: centerX + (index - (count - 1) / 2) * PORT_SPREAD,
            y: size.height,
        })),
    }
}

const LAYOUT_OPTIONS: Record<string, string> = {
    'elk.algorithm': 'layered',
    'elk.direction': 'DOWN',
    'elk.edgeRouting': 'ORTHOGONAL',
    'elk.layered.spacing.nodeNodeBetweenLayers': '44',
    'elk.spacing.nodeNode': '56',
    'elk.spacing.edgeNode': '24',
    'elk.spacing.edgeEdge': '14',
    'elk.spacing.edgeLabel': '4',
    'elk.layered.spacing.edgeNodeBetweenLayers': '20',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    'elk.layered.crossingMinimization.forceNodeModelOrder': 'true',
    // Each path starts in the row under its split, so a path that opens does not push the paths beside it down.
    'elk.layered.layering.strategy': 'LONGEST_PATH_SOURCE',
    'elk.edgeLabels.placement': 'CENTER',
}

// ELK's model-order strategy crashes on nested graphs. Forced node order still keeps the paths in order.
const FLAT_ONLY_OPTIONS: Record<string, string> = {
    'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
}

/** An open frame is taller than the stacks in its row, and they line up with its top, not its middle. */
const ROW_ALIGNMENT = { 'elk.alignment': 'TOP' }

function leafNode(id: string, size: NodeSize, portCount: number): ElkNode {
    const ports = tilePorts(size, portCount)
    return {
        id,
        width: size.width,
        height: size.height,
        layoutOptions: { 'elk.portConstraints': 'FIXED_POS', ...ROW_ALIGNMENT },
        ports: [
            { id: `${id}:in`, ...ports.in, width: 1, height: 1, layoutOptions: { 'elk.port.side': 'NORTH' } },
            ...ports.out.map((point, index) => ({
                id: `${id}:out:${index}`,
                ...point,
                width: 1,
                height: 1,
                layoutOptions: { 'elk.port.side': 'SOUTH' },
            })),
        ],
    }
}

const FRAME_PADDING_OPTION = `[left=${FRAME_PADDING.side}, top=${FRAME_PADDING.top}, right=${FRAME_PADDING.side}, bottom=${FRAME_PADDING.bottom}]`

function elkRootOptions(nested: boolean): Record<string, string> {
    return {
        ...LAYOUT_OPTIONS,
        ...(nested
            ? {
                  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
                  'elk.json.shapeCoords': 'ROOT',
                  'elk.json.edgeCoords': 'ROOT',
              }
            : FLAT_ONLY_OPTIONS),
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
    }
}

/**
 * ELK gives an arrow's label a row of its own. A path whose name shows on its stack or frame has no label on its
 * arrow, so it gets a blank one, and every path of a split starts in the same row. ELK skips a label with no text.
 */
function elkLabels(edge: VisibleEdge): ElkExtendedEdge['labels'] {
    if (edge.label) {
        return [
            { id: `${edge.id}:label`, text: edge.label, width: edgeLabelWidth(edge.label), height: EDGE_LABEL_HEIGHT },
        ]
    }
    return edge.portCount > 1 ? [{ id: `${edge.id}:label`, text: ' ', width: 1, height: EDGE_LABEL_HEIGHT }] : []
}

function elkEdge(edge: VisibleEdge): ElkExtendedEdge {
    return {
        id: edge.id,
        sources: [`${edge.source}:out:${edge.portIndex}`],
        targets: [`${edge.target}:in`],
        labels: elkLabels(edge),
    }
}

function elkFrame(frame: PathFrameSpec): ElkNode {
    return {
        id: frame.id,
        children: [],
        layoutOptions: {
            ...LAYOUT_OPTIONS,
            'elk.padding': FRAME_PADDING_OPTION,
            'elk.nodeSize.constraints': 'MINIMUM_SIZE',
            'elk.nodeSize.minimum': `(${frame.minWidth}, 40)`,
            ...ROW_ALIGNMENT,
        },
    }
}

/**
 * Each node goes into the deepest open frame that holds it, and each frame into its parent frame.
 * ELK keeps the children in the order they are given, so a frame takes the place of its first step: an opened path
 * stays between the same neighbours instead of moving to the end of its row.
 */
function assignFrameChildren(
    root: ElkNode,
    sizes: Record<string, NodeSize>,
    edges: VisibleEdge[],
    frames: PathFrameSpec[]
): void {
    const containers = new Map(frames.map((frame) => [frame.id, elkFrame(frame)]))
    const specs = new Map(frames.map((frame) => [frame.id, frame]))
    const containerOf = (id: string | null | undefined): ElkNode => containers.get(id ?? '') ?? root
    const deepestFrameOf = new Map<string, string>()
    const framesStartingAt = new Map<string, PathFrameSpec[]>()
    ;[...frames]
        .sort((a, b) => a.group.depth - b.group.depth)
        .forEach((frame) => {
            frame.memberIds.forEach((id) => deepestFrameOf.set(id, frame.id))
            const first = frame.memberIds[0] ?? ''
            framesStartingAt.set(first, [...(framesStartingAt.get(first) ?? []), frame])
        })
    const placed = new Set<string>()
    const placeFrame = (frame: PathFrameSpec): void => {
        if (placed.has(frame.id)) {
            return
        }
        placed.add(frame.id)
        const parent = specs.get(frame.parentId ?? '')
        if (parent) {
            placeFrame(parent)
        }
        containerOf(frame.parentId).children?.push(containers.get(frame.id) as ElkNode)
    }
    const portCounts = new Map(edges.map((edge) => [edge.source, edge.portCount]))
    Object.entries(sizes).forEach(([id, size]) => {
        framesStartingAt.get(id)?.forEach(placeFrame)
        containerOf(deepestFrameOf.get(id)).children?.push(leafNode(id, size, portCounts.get(id) ?? 1))
    })
    frames.forEach(placeFrame)
}

function buildElkGraph(sizes: Record<string, NodeSize>, edges: VisibleEdge[], frames: PathFrameSpec[]): ElkNode {
    const root: ElkNode = {
        id: 'root',
        layoutOptions: elkRootOptions(frames.length > 0),
        children: [],
        edges: edges.filter((edge) => sizes[edge.source] && sizes[edge.target]).map(elkEdge),
    }
    assignFrameChildren(root, sizes, edges, frames)
    return root
}

function readLayout(result: ElkNode, frameIds: Set<string>): CanvasLayout {
    const positions: CanvasLayout['positions'] = {}
    const frames: CanvasLayout['frames'] = {}
    const elkEdges: ElkExtendedEdge[] = []
    const walk = (node: ElkNode): void => {
        elkEdges.push(...(node.edges ?? []))
        node.children?.forEach((child) => {
            if (frameIds.has(child.id)) {
                frames[child.id] = {
                    x: child.x ?? 0,
                    y: child.y ?? 0,
                    width: child.width ?? 0,
                    height: child.height ?? 0,
                }
            } else {
                positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 }
            }
            walk(child)
        })
    }
    walk(result)
    const edges: CanvasLayout['edges'] = {}
    elkEdges.forEach((edge) => {
        const section = edge.sections?.[0]
        if (!section) {
            return
        }
        const label = edge.labels?.[0]
        const labelBox =
            label?.x !== undefined && label.y !== undefined
                ? { x: label.x, y: label.y, width: label.width ?? 0, height: label.height ?? 0 }
                : undefined
        edges[edge.id] = {
            points: [section.startPoint, ...(section.bendPoints ?? []), section.endPoint],
            labelBox,
            label: labelBox ? { x: labelBox.x + labelBox.width / 2, y: labelBox.y + labelBox.height / 2 } : undefined,
        }
    })
    return { positions, edges, frames, width: result.width ?? 0, height: result.height ?? 0 }
}

/** ELK ends an arrow at the node box. Pull its start up to the tile, so no arrow floats beside the caption. */
function attachToTiles(layout: CanvasLayout, edges: VisibleEdge[], sizes: Record<string, NodeSize>): CanvasLayout {
    const sourceOf = new Map(edges.map((edge) => [edge.id, edge.source]))
    const attached = Object.fromEntries(
        Object.entries(layout.edges).map(([id, routed]) => {
            const source = sourceOf.get(id)
            const anchor = source ? sizes[source]?.anchor : undefined
            const position = source ? layout.positions[source] : undefined
            if (!anchor || !position) {
                return [id, routed]
            }
            const points = routed.points.map((point) => ({ ...point }))
            points[0].y = position.y + anchor.y + anchor.height / 2 + (anchor.height === TILE_SIZE ? BADGE_ROOM : 0)
            return [id, { ...routed, points }]
        })
    )
    return { ...layout, edges: attached }
}

export async function layoutTileCanvas(
    sizes: Record<string, NodeSize>,
    edges: VisibleEdge[],
    frames: PathFrameSpec[]
): Promise<CanvasLayout> {
    const elk = await getElk()
    const result = await elk.layout(buildElkGraph(sizes, edges, frames))
    return attachToTiles(readLayout(result, new Set(frames.map((frame) => frame.id))), edges, sizes)
}

export function roundedPath(points: Point[]): string {
    if (points.length < 2) {
        return ''
    }
    const radius = 8
    const corners = points.slice(1, -1).map((point, index) => {
        const previous = points[index]
        const next = points[index + 2]
        const inLength = Math.hypot(point.x - previous.x, point.y - previous.y) || 1
        const outLength = Math.hypot(next.x - point.x, next.y - point.y) || 1
        const r = Math.min(radius, inLength / 2, outLength / 2)
        const before = {
            x: point.x - ((point.x - previous.x) / inLength) * r,
            y: point.y - ((point.y - previous.y) / inLength) * r,
        }
        const after = {
            x: point.x + ((next.x - point.x) / outLength) * r,
            y: point.y + ((next.y - point.y) / outLength) * r,
        }
        return `L ${before.x} ${before.y} Q ${point.x} ${point.y} ${after.x} ${after.y}`
    })
    const last = points[points.length - 1]
    return [`M ${points[0].x} ${points[0].y}`, ...corners, `L ${last.x} ${last.y}`].join(' ')
}

export function arrowHead(points: Point[]): string {
    const end = points[points.length - 1]
    const before = points[points.length - 2] ?? { x: end.x, y: end.y - 1 }
    const length = Math.hypot(end.x - before.x, end.y - before.y) || 1
    const [dx, dy] = [(end.x - before.x) / length, (end.y - before.y) / length]
    const back = { x: end.x - dx * 7, y: end.y - dy * 7 }
    return `M ${back.x - dy * 4} ${back.y + dx * 4} L ${end.x} ${end.y} L ${back.x + dy * 4} ${back.y - dx * 4}`
}

export function insertPoint(points: Point[]): Point {
    let best = { length: -1, point: points[0] }
    points.slice(1).forEach((b, index) => {
        const a = points[index]
        const length = Math.abs(b.y - a.y) + Math.abs(b.x - a.x)
        if ((a.x === b.x || a.y === b.y) && length > best.length) {
            best = { length, point: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } }
        }
    })
    return best.point
}

export function entryX(points: Point[] | undefined, top: number, fallback: number): number {
    const crossing = (points ?? []).slice(1).find((b, index) => {
        const a = (points ?? [])[index]
        return a.x === b.x && Math.min(a.y, b.y) <= top && Math.max(a.y, b.y) >= top
    })
    return crossing?.x ?? fallback
}

/** Where the arrow into an open path crosses the top of its frame. */
export function frameEntryX(group: PathGroup, box: Box, layout: CanvasLayout, edges: VisibleEdge[]): number {
    const entry = edges.find((edge) => edge.originalEdgeKeys.includes(getEdgeId(group.entryEdge)))
    return entryX(entry ? layout.edges[entry.id]?.points : undefined, box.y, box.x + box.width / 2)
}

export function canvasBounds(layout: CanvasLayout, sizes: Record<string, NodeSize>): Box | undefined {
    const boxes: Box[] = [
        ...Object.entries(layout.positions).flatMap(([id, position]) =>
            sizes[id] ? [{ ...position, width: sizes[id].width, height: sizes[id].height }] : []
        ),
        ...Object.values(layout.frames),
        ...Object.values(layout.edges).flatMap((edge) => [
            ...edge.points.map((point) => ({ ...point, width: 0, height: 0 })),
            ...(edge.labelBox ? [edge.labelBox] : []),
        ]),
    ]
    if (!boxes.length) {
        return undefined
    }
    const left = Math.min(...boxes.map((box) => box.x))
    const top = Math.min(...boxes.map((box) => box.y))
    const right = Math.max(...boxes.map((box) => box.x + box.width))
    const bottom = Math.max(...boxes.map((box) => box.y + box.height))
    return { x: left, y: top, width: right - left, height: bottom - top }
}
