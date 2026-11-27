import type { Point } from '../../Workflows/hogflows/editor/tile-canvas/tileCanvasModel'
import type { AdventPollShares } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_QUESTIONS, adventQuestionBefore } from '../adventContent'
import { ADVENT_TRIGGER_ID, AdventDoor, AdventGraph, AdventLink } from '../adventGraph'

export const ADVENT_FLOW_DOOR = { width: 70, height: 74 }
export const ADVENT_FLOW_EXIT_ID = 'exit'
export const ADVENT_FLOW_PHONE_WIDTH = 390

export type AdventFlowOrientation = 'rows' | 'column'
export type AdventFlowLane = 'upper' | 'lower'
export type AdventFlowSide = 'left' | 'right'

export interface AdventFlowRect {
    x: number
    y: number
    width: number
    height: number
}

export interface AdventFlowHover {
    side: AdventFlowSide
    rect: AdventFlowRect
}

export interface AdventFlowNode {
    id: string
    kind: 'trigger' | 'door' | 'exit'
    door: AdventDoor | null
    row: number
    lane: AdventFlowLane | null
    tile: AdventFlowRect
    caption: AdventFlowRect
    hover: AdventFlowHover | null
}

export interface AdventFlowEdge {
    id: string
    source: string
    target: string
    points: Point[]
    walked: boolean
    label: string | null
    share: number | null
    labelAt: Point | null
}

export interface AdventFlowLayout {
    orientation: AdventFlowOrientation
    width: number
    height: number
    nodes: AdventFlowNode[]
    edges: AdventFlowEdge[]
}

type Gap = 'step' | 'split' | 'merge'

interface Rank {
    id: string
    day: number
    doors: AdventDoor[]
}

interface Slot {
    id: string
    door: AdventDoor | null
    lane: AdventFlowLane | null
}

const { width: DOOR_WIDTH, height: DOOR_HEIGHT } = ADVENT_FLOW_DOOR
const CAPTION = { height: 30, gap: 14 }
const PORT = 7
const CORNER_RUN = 16

const isLaneDay = (day: number): boolean => adventQuestionBefore(day) !== null

function gapBefore(day: number): Gap {
    if (day <= 1 || day > ADVENT_LAST_DAY) {
        return 'step'
    }
    if (adventQuestionBefore(day) === day - 1) {
        return 'split'
    }
    return isLaneDay(day - 1) && !isLaneDay(day) ? 'merge' : 'step'
}

function laneOf(door: AdventDoor): AdventFlowLane | null {
    return door.id.endsWith('-upper') ? 'upper' : door.id.endsWith('-lower') ? 'lower' : null
}

function ranksOf(graph: AdventGraph): Rank[] {
    const days = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)
    return [
        { id: ADVENT_TRIGGER_ID, day: 0, doors: [] },
        ...days.map((day) => ({ id: `day-${day}`, day, doors: graph.doors.filter((door) => door.day === day) })),
        { id: ADVENT_FLOW_EXIT_ID, day: ADVENT_LAST_DAY + 1, doors: [] },
    ]
}

function slotsOf(rank: Rank): Slot[] {
    if (!rank.doors.length) {
        return [{ id: rank.id, door: null, lane: null }]
    }
    return rank.doors.map((door) => ({ id: door.id, door, lane: laneOf(door) }))
}

function nodeOf(
    slot: Slot,
    row: number,
    tile: AdventFlowRect,
    caption: AdventFlowRect,
    hover: AdventFlowHover | null = null
): AdventFlowNode {
    const kind = slot.door ? 'door' : slot.id === ADVENT_FLOW_EXIT_ID ? 'exit' : 'trigger'
    return { id: slot.id, kind, door: slot.door, row, lane: slot.lane, tile, caption, hover }
}

const ROWS_WIDTH = 1200
const ROWS_MARGIN = { left: 64, right: 48, top: 12 }
const ROW_BREAKS = [9, 17]
const ROWS_LANE_OFFSET = (DOOR_HEIGHT + 22) / 2
const ROWS_CAPTION_WIDTH = 100
const ROW_REACH = ROWS_LANE_OFFSET + DOOR_HEIGHT / 2 + CAPTION.gap + CAPTION.height
const ROW_PITCH = 2 * ROW_REACH + 16
const ROWS_WRAP_X = ROWS_MARGIN.left - 28
const GAP_WEIGHT: Record<Gap, number> = { step: 1, split: 2.6, merge: 1.2 }
const HOVER = { width: 180, gap: 10, leafReach: 26 }

function rowsHover(tile: AdventFlowRect): AdventFlowHover {
    const right = tile.x + tile.width + HOVER.gap
    const side = right + HOVER.width <= ROWS_WIDTH ? 'right' : 'left'
    const x = side === 'right' ? right : tile.x - HOVER.leafReach - HOVER.gap - HOVER.width
    return { side, rect: { x, y: tile.y, width: HOVER.width, height: tile.height } }
}

const rowOfDay = (day: number): number => ROW_BREAKS.filter((start) => day >= start).length
const rowCenter = (row: number): number => ROWS_MARGIN.top + ROW_REACH + row * ROW_PITCH

function rowsSlot(slot: Slot, x: number, row: number): AdventFlowNode {
    const sign = slot.lane === 'upper' ? -1 : slot.lane === 'lower' ? 1 : 0
    const tile = {
        x,
        y: rowCenter(row) + sign * ROWS_LANE_OFFSET - DOOR_HEIGHT / 2,
        width: DOOR_WIDTH,
        height: DOOR_HEIGHT,
    }
    const captionY = slot.lane === 'upper' ? tile.y - CAPTION.gap - CAPTION.height : tile.y + DOOR_HEIGHT + CAPTION.gap
    const caption = {
        x: x + DOOR_WIDTH / 2 - ROWS_CAPTION_WIDTH / 2,
        y: captionY,
        width: ROWS_CAPTION_WIDTH,
        height: CAPTION.height,
    }
    return nodeOf(slot, row, tile, caption, slot.door ? rowsHover(tile) : null)
}

function rowsNodes(ranks: Rank[]): AdventFlowNode[] {
    const rows = [0, 1, 2].map((row) => ranks.filter((rank) => rowOfDay(rank.day) === row))
    const weightOf = (rank: Rank): number => GAP_WEIGHT[gapBefore(rank.day)]
    const room = ROWS_WIDTH - ROWS_MARGIN.left - ROWS_MARGIN.right
    const unit = Math.min(
        ...rows.map((row) => {
            const weights = row.slice(1).reduce((sum, rank) => sum + weightOf(rank), 0)
            return (room - row.length * DOOR_WIDTH) / weights
        })
    )
    return rows.flatMap((row, rowIndex) => {
        let x = ROWS_MARGIN.left
        return row.flatMap((rank, index) => {
            x += index > 0 ? DOOR_WIDTH + unit * weightOf(rank) : 0
            return slotsOf(rank).map((slot) => rowsSlot(slot, x, rowIndex))
        })
    })
}

const COLUMN_X = { main: 24, lower: 206 }
const COLUMN_TOP = 24
const COLUMN_BOTTOM = 40
const COLUMN_CAPTION_GAP = 10
const COLUMN_GAP: Record<Gap, number> = { step: 40, split: 72, merge: 40 }

function columnCaption(slot: Slot, tile: AdventFlowRect): AdventFlowRect {
    const x = tile.x + DOOR_WIDTH + COLUMN_CAPTION_GAP
    const end = slot.lane === 'upper' ? COLUMN_X.lower - COLUMN_CAPTION_GAP : ADVENT_FLOW_PHONE_WIDTH - 8
    return { x, y: tile.y + DOOR_HEIGHT / 2 - CAPTION.height / 2, width: end - x, height: CAPTION.height }
}

function columnNodes(ranks: Rank[]): { nodes: AdventFlowNode[]; height: number } {
    let y = COLUMN_TOP
    const nodes = ranks.flatMap((rank, index) => {
        y += index > 0 ? DOOR_HEIGHT + COLUMN_GAP[gapBefore(rank.day)] : 0
        return slotsOf(rank).map((slot) => {
            const x = slot.lane === 'lower' ? COLUMN_X.lower : COLUMN_X.main
            const tile = { x, y, width: DOOR_WIDTH, height: DOOR_HEIGHT }
            return nodeOf(slot, 0, tile, columnCaption(slot, tile))
        })
    })
    return { nodes, height: y + DOOR_HEIGHT + COLUMN_BOTTOM }
}

interface Route {
    from: Point
    to: Point
    source: AdventFlowRect
    target: AdventFlowRect
    isSplit: boolean
    isMerge: boolean
}

const centerOf = (rect: AdventFlowRect): Point => ({ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 })

function wrapRoute({ from, to, source, target }: Route, gutter: number): Point[] {
    const out = source.x + source.width
    return [
        { x: out, y: from.y },
        { x: out + 22, y: from.y },
        { x: out + 22, y: gutter },
        { x: ROWS_WRAP_X, y: gutter },
        { x: ROWS_WRAP_X, y: to.y },
        { x: target.x, y: to.y },
    ]
}

function rowsRoute(route: Route, sourceRow: number, targetRow: number): Point[] {
    const { from, to, source, target, isSplit, isMerge } = route
    if (sourceRow !== targetRow) {
        return wrapRoute(route, (rowCenter(sourceRow) + rowCenter(targetRow)) / 2)
    }
    const out = source.x + source.width
    if (from.y === to.y) {
        return [
            { x: out, y: from.y },
            { x: target.x, y: to.y },
        ]
    }
    if (isSplit) {
        const port = to.y < from.y ? -PORT : PORT
        return [
            { x: out, y: from.y + port },
            { x: out + CORNER_RUN, y: from.y + port },
            { x: out + CORNER_RUN, y: to.y },
            { x: target.x, y: to.y },
        ]
    }
    const port = isMerge ? (from.y < to.y ? -PORT : PORT) : 0
    return [
        { x: out, y: from.y },
        { x: target.x - CORNER_RUN, y: from.y },
        { x: target.x - CORNER_RUN, y: to.y + port },
        { x: target.x, y: to.y + port },
    ]
}

function columnRoute({ from, to, source, target, isSplit, isMerge }: Route): Point[] {
    const out = source.y + source.height
    if (from.x === to.x) {
        return [
            { x: from.x, y: out },
            { x: to.x, y: target.y },
        ]
    }
    if (isSplit) {
        const port = to.x > from.x ? PORT : -PORT
        return [
            { x: from.x + port, y: out },
            { x: from.x + port, y: out + CORNER_RUN },
            { x: to.x, y: out + CORNER_RUN },
            { x: to.x, y: target.y },
        ]
    }
    const port = isMerge ? (from.x > to.x ? PORT : -PORT) : 0
    return [
        { x: from.x, y: out },
        { x: from.x, y: target.y - CORNER_RUN },
        { x: to.x + port, y: target.y - CORNER_RUN },
        { x: to.x + port, y: target.y },
    ]
}

function alongLastRun(points: Point[], share: number): Point {
    const [a, b] = points.slice(-2)
    return { x: a.x + (b.x - a.x) * share, y: a.y + (b.y - a.y) * share }
}

function linksOf(graph: AdventGraph): Pick<AdventLink, 'id' | 'from' | 'to' | 'walked'>[] {
    const lastDoors = graph.doors.filter((door) => door.day === ADVENT_LAST_DAY)
    return [
        ...graph.links,
        ...lastDoors.map((door) => ({
            id: `${door.id}>${ADVENT_FLOW_EXIT_ID}`,
            from: door.id,
            to: ADVENT_FLOW_EXIT_ID,
            walked: door.status === 'open',
        })),
    ]
}

function edgesOf(
    graph: AdventGraph,
    nodes: AdventFlowNode[],
    shares: AdventPollShares,
    orientation: AdventFlowOrientation
): AdventFlowEdge[] {
    const byId = new Map(nodes.map((node) => [node.id, node]))
    const links = linksOf(graph)
    const incoming = (id: string): number => links.filter((link) => link.to === id).length
    return links.flatMap((link): AdventFlowEdge[] => {
        const [source, target] = [byId.get(link.from), byId.get(link.to)]
        if (!source || !target) {
            return []
        }
        const question = source.door ? (ADVENT_QUESTIONS[source.door.day] ?? null) : null
        const route: Route = {
            from: centerOf(source.tile),
            to: centerOf(target.tile),
            source: source.tile,
            target: target.tile,
            isSplit: !!question,
            isMerge: incoming(target.id) > 1,
        }
        const points = orientation === 'rows' ? rowsRoute(route, source.row, target.row) : columnRoute(route)
        const option = question ? (source.door?.answer ?? question.options[target.lane === 'lower' ? 1 : 0]) : null
        return [
            {
                id: link.id,
                source: link.from,
                target: link.to,
                points,
                walked: link.walked,
                label: option?.label ?? null,
                share: option && source.door ? (shares[source.door.day]?.[option.id] ?? null) : null,
                labelAt: option ? alongLastRun(points, orientation === 'rows' ? 0.5 : 0.66) : null,
            },
        ]
    })
}

export function adventFlowLayout(
    graph: AdventGraph,
    shares: AdventPollShares,
    orientation: AdventFlowOrientation
): AdventFlowLayout {
    const ranks = ranksOf(graph)
    if (orientation === 'rows') {
        const nodes = rowsNodes(ranks)
        const height = rowCenter(2) + ROW_REACH + ROWS_MARGIN.top
        return { orientation, width: ROWS_WIDTH, height, nodes, edges: edgesOf(graph, nodes, shares, orientation) }
    }
    const { nodes, height } = columnNodes(ranks)
    return {
        orientation,
        width: ADVENT_FLOW_PHONE_WIDTH,
        height,
        nodes,
        edges: edgesOf(graph, nodes, shares, orientation),
    }
}
