import type { ElkExtendedEdge, ElkLabel, ElkNode, ElkPort } from 'elkjs/lib/elk.bundled.js'

import { getElk } from 'lib/elk'
import { groupBy } from 'lib/utils/arrays'

import { getEdgeId } from '../../edgeId'
import { isInPathGroup, openPathFrames, PathGroup, Point, VisibleEdge, VisibleNode } from './tileCanvasModel'

export const TILE_SIZE = 64
export const EDGE_LABEL_HEIGHT = 22
const BADGE_ROOM = 10
const PORT_SPREAD = 14
const PORT_MARGIN = 4
const ARROW_HALF_WIDTH = 4
// Arrowheads closer than their width draw as one shape, so many arrows into one step spread past its tile.
const MIN_ARROWHEAD_GAP = 2 * ARROW_HALF_WIDTH + 2
// ELK can move a split's targets after the ports are pinned, which changes the order the ports need.
const MAX_LAYOUT_PASSES = 4
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

interface PortOrder {
    out: Map<string, number>
    in: Map<string, number>
}

function portSpread(size: NodeSize, count: number, minGap: number): number {
    const room = (size.anchor?.width ?? size.width) - 2 * PORT_MARGIN
    return count > 1 ? Math.min(PORT_SPREAD, Math.max(minGap, room / (count - 1))) : PORT_SPREAD
}

function portX(size: NodeSize, slot: number, count: number, minGap: number): number {
    return tileEntry({ x: 0, y: 0 }, size).x + (slot - (count - 1) / 2) * portSpread(size, count, minGap)
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

const IN = ':in'
const OUT = ':out'

/** Each arrow has a port of its own at both ends, so ELK never merges two arrows into one run. */
function leafNode(id: string, size: NodeSize, edgesIn: VisibleEdge[], edgesOut: VisibleEdge[]): ElkNode {
    const port = (portId: string, side: 'NORTH' | 'SOUTH'): ElkPort => ({
        id: portId,
        width: 1,
        height: 1,
        layoutOptions: { 'elk.port.side': side },
    })
    return {
        id,
        width: size.width,
        height: size.height,
        layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE', ...ROW_ALIGNMENT },
        ports: [
            ...edgesIn.map((edge) => port(edge.id + IN, 'NORTH')),
            ...edgesOut.map((edge) => port(edge.id + OUT, 'SOUTH')),
        ],
    }
}

/** Pins each port under the tile, in its slot, because ELK centers free ports on the whole node and its caption. */
function pinPorts(node: ElkNode, sizes: Record<string, NodeSize>, order: PortOrder): ElkNode {
    const children = node.children?.map((child) => pinPorts(child, sizes, order))
    const size = sizes[node.id]
    if (!size || !node.ports) {
        return { ...node, children }
    }
    const into = node.ports.filter((port) => port.id.endsWith(IN)).length
    const ports = node.ports.map((port) => {
        const isIn = port.id.endsWith(IN)
        const edgeId = port.id.slice(0, -(isIn ? IN : OUT).length)
        const slot = (isIn ? order.in : order.out).get(edgeId) ?? 0
        const count = isIn ? into : node.ports!.length - into
        const x = portX(size, slot, count, isIn ? MIN_ARROWHEAD_GAP : 0)
        return { ...port, x, y: isIn ? 0 : size.height }
    })
    return {
        ...node,
        children,
        ports,
        layoutOptions: { ...node.layoutOptions, 'elk.portConstraints': 'FIXED_POS' },
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
    // An inline label sits on its arrow. Otherwise ELK puts it beside the arrow, closer to the next arrow than to its own.
    const label = (text: string, width: number): ElkLabel => ({
        id: `${edge.id}:label`,
        text,
        width,
        height: EDGE_LABEL_HEIGHT,
        layoutOptions: { 'elk.edgeLabels.inline': 'true' },
    })
    if (edge.label) {
        return [label(edge.label, edgeLabelWidth(edge.label))]
    }
    return edge.portCount > 1 ? [label(' ', 1)] : []
}

function elkEdge(edge: VisibleEdge): ElkExtendedEdge {
    return {
        id: edge.id,
        sources: [edge.id + OUT],
        targets: [edge.id + IN],
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
    const byPortIndex = [...edges].sort((a, b) => a.portIndex - b.portIndex)
    Object.entries(sizes).forEach(([id, size]) => {
        framesStartingAt.get(id)?.forEach(placeFrame)
        const edgesIn = byPortIndex.filter((edge) => edge.target === id)
        const edgesOut = byPortIndex.filter((edge) => edge.source === id)
        containerOf(deepestFrameOf.get(id)).children?.push(leafNode(id, size, edgesIn, edgesOut))
    })
    frames.forEach(placeFrame)
}

function buildElkGraph(sizes: Record<string, NodeSize>, edges: VisibleEdge[], frames: PathFrameSpec[]): ElkNode {
    const root: ElkNode = {
        id: 'root',
        layoutOptions: elkRootOptions(frames.length > 0),
        children: [],
        edges: edges.map(elkEdge),
    }
    assignFrameChildren(root, sizes, edges, frames)
    return root
}

/** Slots edges left to right. Arrows from one split into one step tie, and keep `rank` order, so both ends agree. */
function slotsBy(
    edges: VisibleEdge[],
    compare: (a: VisibleEdge, b: VisibleEdge) => number,
    rank: (edge: VisibleEdge) => number
): Map<string, number> {
    const ordered = [...edges].sort((a, b) => compare(a, b) || rank(a) - rank(b))
    return new Map(ordered.map((edge, slot) => [edge.id, slot]))
}

function xAt(points: Point[], y: number): number {
    const down = points.findIndex((start, index) => {
        const end = points[index + 1]
        return !!end && end.x === start.x && y >= Math.min(start.y, end.y) && y <= Math.max(start.y, end.y)
    })
    return down >= 0 ? points[down].x : (points.at(-1)?.x ?? 0)
}

/**
 * Two arrows that do not cross keep their left-to-right order at every height they share. So two arrows out of one step
 * take the order they have just above the nearer of their ends, and two arrows into one step the order just below the
 * nearer of their starts.
 */
function portOrderOf(layout: CanvasLayout, edges: VisibleEdge[]): PortOrder {
    const out = new Map<string, number>()
    const into = new Map<string, number>()
    const pointsOf = (edge: VisibleEdge): Point[] => layout.edges[edge.id]?.points ?? []
    const endY = (edge: VisibleEdge): number => pointsOf(edge).at(-1)?.y ?? 0
    const startY = (edge: VisibleEdge): number => pointsOf(edge)[0]?.y ?? 0
    const xAbove = (a: VisibleEdge, b: VisibleEdge): number => {
        if (a.target === b.target) {
            return 0
        }
        const y = Math.min(endY(a), endY(b)) - 1
        return xAt(pointsOf(a), y) - xAt(pointsOf(b), y)
    }
    const xBelow = (a: VisibleEdge, b: VisibleEdge): number => {
        if (a.source === b.source) {
            return 0
        }
        const y = Math.max(startY(a), startY(b)) + 1
        return xAt(pointsOf(a), y) - xAt(pointsOf(b), y)
    }
    Object.values(groupBy(edges, (edge) => edge.source)).forEach((fromOneStep) =>
        slotsBy(fromOneStep, xAbove, (edge) => edge.portIndex).forEach((slot, id) => out.set(id, slot))
    )
    Object.values(groupBy(edges, (edge) => edge.target)).forEach((intoOneStep) =>
        slotsBy(intoOneStep, xBelow, (edge) => out.get(edge.id) ?? 0).forEach((slot, id) => into.set(id, slot))
    )
    return { out, in: into }
}

const sameOrder = (one: PortOrder, other: PortOrder): boolean =>
    [...one.out].every(([id, slot]) => other.out.get(id) === slot) &&
    [...one.in].every(([id, slot]) => other.in.get(id) === slot)

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

/** `stopIfStale` throws when a newer layout replaces this one, so a stale layout sends no more passes to the shared ELK worker. */
export async function layoutTileCanvas(
    sizes: Record<string, NodeSize>,
    edges: VisibleEdge[],
    frames: PathFrameSpec[],
    stopIfStale: () => void = () => {}
): Promise<CanvasLayout> {
    const elk = await getElk()
    const frameIds = new Set(frames.map((frame) => frame.id))
    const shown = edges.filter((edge) => sizes[edge.source] && sizes[edge.target])
    const graph = (): ElkNode => buildElkGraph(sizes, shown, frames)
    // The first pass only finds where each arrow goes. Later passes pin the ports in that order until it holds.
    let layout = readLayout(await elk.layout(graph()), frameIds)
    let order: PortOrder | null = null
    for (let pass = 1; pass < MAX_LAYOUT_PASSES; pass++) {
        stopIfStale()
        const next = portOrderOf(layout, shown)
        if (order && sameOrder(order, next)) {
            break
        }
        order = next
        layout = readLayout(await elk.layout(pinPorts(graph(), sizes, order)), frameIds)
    }
    return attachToTiles(layout, edges, sizes)
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
    const [wx, wy] = [dy * ARROW_HALF_WIDTH, dx * ARROW_HALF_WIDTH]
    return `M ${back.x - wx} ${back.y + wy} L ${end.x} ${end.y} L ${back.x + wx} ${back.y - wy}`
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

const QUICK_ADD_GAP = 14

/** Where an arrow's + sits: past its label when it has one, else in the middle of its longest straight run. */
export function quickAddPoint(routed: RoutedEdge, label: string | undefined): Point {
    if (label && routed.label) {
        return { x: routed.label.x + edgeLabelWidth(label) / 2 + QUICK_ADD_GAP, y: routed.label.y }
    }
    return insertPoint(routed.points)
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
