import type { AppMetricsTotalsRequest } from 'lib/components/AppMetrics/appMetricsLogic'

import { getEdgeId } from '../../edgeId'
import type { CreateActionType, HogFlowEditorActionMetrics } from '../../hogFlowEditorLogic'
import { getWorkflowBranchLabel, isBranchingAction } from '../../tree/workflowTree'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../types'

export type FlowGraph = Pick<HogFlow, 'actions' | 'edges'>

interface EdgeIndex {
    outgoing: Map<string, HogFlowEdge[]>
    /** The step every path out of a step passes through next, where its paths join again. */
    joinOf: Map<string, string>
}

const edgeIndexes = new WeakMap<HogFlowEdge[], EdgeIndex>()
const actionIndexes = new WeakMap<HogFlowAction[], Map<string, HogFlowAction>>()

function byPathOrder(a: HogFlowEdge, b: HogFlowEdge): number {
    return a.type !== b.type ? (a.type === 'branch' ? -1 : 1) : (a.index ?? 0) - (b.index ?? 0)
}

function outgoingIndex(edges: HogFlowEdge[]): Map<string, HogFlowEdge[]> {
    const outgoing = new Map<string, HogFlowEdge[]>()
    edges.forEach((edge) => {
        const list = outgoing.get(edge.from)
        if (list) {
            list.push(edge)
        } else {
            outgoing.set(edge.from, [edge])
        }
    })
    outgoing.forEach((list) => list.sort(byPathOrder))
    return outgoing
}

const END_OF_FLOW = '\u0000end'

function postorderToEnd(edges: HogFlowEdge[], outgoing: Map<string, HogFlowEdge[]>): string[] {
    const incoming = new Map<string, string[]>()
    const steps = new Set<string>()
    edges.forEach((edge) => {
        steps.add(edge.from).add(edge.to)
        incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge.from])
    })
    const lastSteps = [...steps].filter((id) => !outgoing.has(id))
    const seen = new Set<string>([END_OF_FLOW])
    const postorder: string[] = []
    const pending: [id: string, isDone: boolean][] = [
        [END_OF_FLOW, true],
        ...lastSteps.map((id): [string, boolean] => [id, false]),
    ]
    while (pending.length) {
        const [id, isDone] = pending.pop() as [string, boolean]
        if (isDone) {
            postorder.push(id)
        } else if (!seen.has(id)) {
            seen.add(id)
            pending.push([id, true], ...(incoming.get(id) ?? []).map((from): [string, boolean] => [from, false]))
        }
    }
    return postorder
}

/**
 * Post-dominators, by the iterative algorithm of Cooper, Harvey and Kennedy on the reversed graph, with one end
 * after every last step. A split's paths join at its immediate post-dominator.
 */
function joinSteps(edges: HogFlowEdge[], outgoing: Map<string, HogFlowEdge[]>): Map<string, string> {
    const postorder = postorderToEnd(edges, outgoing)
    const rank = new Map(postorder.map((id, index) => [id, index]))
    const idom = new Map<string, string>([[END_OF_FLOW, END_OF_FLOW]])
    const nextSteps = (id: string): string[] => outgoing.get(id)?.map((edge) => edge.to) ?? [END_OF_FLOW]
    const intersect = (first: string, second: string): string => {
        let [a, b] = [first, second]
        while (a !== b) {
            while ((rank.get(a) ?? 0) < (rank.get(b) ?? 0)) {
                a = idom.get(a) as string
            }
            while ((rank.get(b) ?? 0) < (rank.get(a) ?? 0)) {
                b = idom.get(b) as string
            }
        }
        return a
    }
    const reversePostorder = postorder.slice(0, -1).reverse()
    let changed = true
    while (changed) {
        changed = false
        reversePostorder.forEach((id) => {
            const processed = nextSteps(id).filter((next) => idom.has(next))
            const dominator = processed.slice(1).reduce(intersect, processed[0])
            if (dominator !== undefined && idom.get(id) !== dominator) {
                idom.set(id, dominator)
                changed = true
            }
        })
    }
    idom.forEach((dominator, id) => dominator === END_OF_FLOW && idom.delete(id))
    return idom
}

function edgeIndex(workflow: FlowGraph): EdgeIndex {
    let index = edgeIndexes.get(workflow.edges)
    if (!index) {
        const outgoing = outgoingIndex(workflow.edges)
        index = { outgoing, joinOf: joinSteps(workflow.edges, outgoing) }
        edgeIndexes.set(workflow.edges, index)
    }
    return index
}

export function actionsById(workflow: Pick<HogFlow, 'actions'>): Map<string, HogFlowAction> {
    let index = actionIndexes.get(workflow.actions)
    if (!index) {
        index = new Map(workflow.actions.map((action) => [action.id, action]))
        actionIndexes.set(workflow.actions, index)
    }
    return index
}

export function outgoingEdges(workflow: FlowGraph, actionId: string): HogFlowEdge[] {
    return edgeIndex(workflow).outgoing.get(actionId) ?? []
}

/**
 * Every step reachable from the starts, each before the steps it leads to. The paths of a split follow each
 * other in path order, so one path's steps stay together and the step where they join comes after all of them.
 */
export function executionOrder(
    workflow: FlowGraph,
    startIds: readonly string[],
    canVisit: (id: string) => boolean = () => true
): string[] {
    const seen = new Set<string>()
    return startIds.flatMap((startId) => {
        const finished: string[] = []
        const pending: [id: string, isDone: boolean][] = [[startId, false]]
        while (pending.length) {
            const [id, isDone] = pending.pop() as [string, boolean]
            if (isDone) {
                finished.push(id)
            } else if (!seen.has(id) && canVisit(id)) {
                seen.add(id)
                pending.push(
                    [id, true],
                    ...outgoingEdges(workflow, id).map((edge): [string, boolean] => [edge.to, false])
                )
            }
        }
        return finished.reverse()
    })
}

function workflowOrder(workflow: FlowGraph): Map<string, number> {
    const starts = [
        ...workflow.actions.filter((action) => action.type === 'trigger'),
        ...workflow.actions.filter((action) => action.type !== 'trigger'),
    ].map((action) => action.id)
    return new Map(executionOrder(workflow, starts).map((id, index) => [id, index]))
}

export interface PathGroup {
    id: string
    branchActionId: string
    entryEdge: HogFlowEdge
    label: string
    memberIds: string[]
    members: ReadonlySet<string>
    parentId: string | null
    depth: number
}

const PATH_COLORS = [
    'var(--data-color-1)',
    'var(--data-color-13)',
    'var(--data-color-7)',
    'var(--data-color-4)',
    'var(--data-color-3)',
]

export function pathColor(edge: Pick<HogFlowEdge, 'type' | 'index'>): string {
    return edge.type === 'branch' ? PATH_COLORS[(edge.index ?? 0) % PATH_COLORS.length] : 'var(--color-text-secondary)'
}

export function tint(color: string, percent: number): string {
    return `color-mix(in srgb, ${color} ${percent}%, transparent)`
}

export function pathGroupId(edge: HogFlowEdge): string {
    return `path:${edge.from}:${edge.type}:${edge.index ?? ''}`
}

const SHARED = -1

/**
 * Which path of a split reaches each step before the paths join: its index, or SHARED when more than one does.
 * Each step changes its label at most twice, so one pass over the edges between the split and the join does.
 */
function pathOfStep(workflow: FlowGraph, entries: string[], joinId: string | undefined): Map<string, number> {
    const label = new Map<string, number>()
    const pending: [id: string, path: number][] = entries.map((id, path) => [id, path])
    while (pending.length) {
        const [id, path] = pending.pop() as [string, number]
        const current = label.get(id)
        if (id === joinId || current === path || current === SHARED) {
            continue
        }
        const next = current === undefined ? path : SHARED
        label.set(id, next)
        outgoingEdges(workflow, id).forEach((edge) => pending.push([edge.to, next]))
    }
    return label
}

function pathsOf(workflow: FlowGraph, splitAction: HogFlowAction): PathGroup[] {
    const outgoing = outgoingEdges(workflow, splitAction.id)
    if (outgoing.length < 2) {
        return []
    }
    const label = pathOfStep(
        workflow,
        outgoing.map((edge) => edge.to),
        edgeIndex(workflow).joinOf.get(splitAction.id)
    )
    return outgoing.flatMap((edge, path) => {
        const memberIds = executionOrder(workflow, [edge.to], (id) => label.get(id) === path)
        // A single step reads better on the canvas as itself than inside a group of one.
        if (memberIds.length < 2) {
            return []
        }
        return [
            {
                id: pathGroupId(edge),
                branchActionId: splitAction.id,
                entryEdge: edge,
                label: getWorkflowBranchLabel(splitAction, edge),
                memberIds,
                members: new Set(memberIds),
                parentId: null,
                depth: 0,
            },
        ]
    })
}

function loopsBackToItsSplit(group: PathGroup): boolean {
    return group.members.has(group.branchActionId)
}

function encloses(outer: PathGroup, inner: PathGroup): boolean {
    return outer.memberIds.length > inner.memberIds.length && inner.memberIds.every((id) => outer.members.has(id))
}

/** A path's parent is the smallest other path that holds its split and all of its steps. */
function parentsOf(groups: PathGroup[]): Map<string, string> {
    const holding = new Map<string, PathGroup[]>()
    ;[...groups]
        .sort((a, b) => a.memberIds.length - b.memberIds.length)
        .forEach((group) =>
            group.memberIds.forEach((id) => {
                const holders = holding.get(id)
                holders ? holders.push(group) : holding.set(id, [group])
            })
        )
    const parents = new Map<string, string>()
    groups.forEach((group) => {
        const parent = holding.get(group.branchActionId)?.find((other) => encloses(other, group))
        if (parent) {
            parents.set(group.id, parent.id)
        }
    })
    return parents
}

export function computePathGroups(workflow: FlowGraph): PathGroup[] {
    // A path that leads back to its own split has no end to fold into a stack, so its steps stay plain tiles.
    const groups = workflow.actions
        .filter(isBranchingAction)
        .flatMap((action) => pathsOf(workflow, action))
        .filter((group) => !loopsBackToItsSplit(group))
    // A parent holds strictly more steps than its child, so the parent chain can never loop.
    const parents = parentsOf(groups)
    const depths = new Map<string, number>()
    const depthOf = (id: string): number => {
        const parentId = parents.get(id)
        if (!parentId) {
            return 0
        }
        if (!depths.has(id)) {
            depths.set(id, depthOf(parentId) + 1)
        }
        return depths.get(id) as number
    }
    return groups.map((group) => ({ ...group, parentId: parents.get(group.id) ?? null, depth: depthOf(group.id) }))
}

function ancestorsOf(groups: PathGroup[], group: PathGroup): PathGroup[] {
    const byId = new Map(groups.map((other) => [other.id, other]))
    const ancestors: PathGroup[] = []
    for (let parent = byId.get(group.parentId ?? ''); parent; parent = byId.get(parent.parentId ?? '')) {
        ancestors.push(parent)
    }
    return ancestors
}

function hasOpenAncestors(groups: PathGroup[], open: ReadonlySet<string>): (group: PathGroup) => boolean {
    const byId = new Map(groups.map((group) => [group.id, group]))
    return (group) => {
        for (let parent = byId.get(group.parentId ?? ''); parent; parent = byId.get(parent.parentId ?? '')) {
            if (!open.has(parent.id)) {
                return false
            }
        }
        return true
    }
}

export function openPathFrames(groups: PathGroup[], openGroupIds: readonly string[]): PathGroup[] {
    const open = new Set(openGroupIds)
    const isShown = hasOpenAncestors(groups, open)
    return groups.filter((group) => open.has(group.id) && isShown(group))
}

export function collapsedPathStacks(groups: PathGroup[], openGroupIds: readonly string[]): PathGroup[] {
    const open = new Set(openGroupIds)
    const isShown = hasOpenAncestors(groups, open)
    return groups.filter((group) => !open.has(group.id) && isShown(group))
}

export function pathActions(workflow: Pick<HogFlow, 'actions'>, group: PathGroup): HogFlowAction[] {
    const byId = actionsById(workflow)
    return group.memberIds.flatMap((id) => byId.get(id) ?? [])
}

/** The start and end of a workflow cannot be copied, moved or deleted, so they have no step menu. */
export function hasStepMenu(action: Pick<HogFlowAction, 'type'>): boolean {
    return action.type !== 'trigger' && action.type !== 'exit'
}

export function isInPathGroup(group: PathGroup, node: VisibleNode): boolean {
    return group.members.has(node.kind === 'step' ? node.id : node.group.branchActionId)
}

export type VisibleNode =
    | { kind: 'step'; id: string; action: HogFlowAction }
    | { kind: 'stack'; id: string; group: PathGroup }

export interface VisibleEdge {
    id: string
    source: string
    target: string
    portIndex: number
    portCount: number
    label?: string
    /** The workflow edge a step can be inserted into. Absent where the arrow leads into or out of a stack. */
    insertEdge?: HogFlowEdge
    originalEdgeKeys: string[]
}

export interface VisibleGraph {
    nodes: VisibleNode[]
    edges: VisibleEdge[]
}

interface Collapsed {
    stackOf: Map<string, string>
    namedElsewhere: Set<string>
    actionsById: Map<string, HogFlowAction>
}

function visibleNodes(workflow: FlowGraph, stacks: PathGroup[], { stackOf }: Collapsed): VisibleNode[] {
    const order = workflowOrder(workflow)
    const orderOf = (node: VisibleNode): number =>
        order.get(node.kind === 'step' ? node.id : node.group.memberIds[0]) ?? 0
    return [
        ...workflow.actions
            .filter((action) => !stackOf.has(action.id))
            .map((action): VisibleNode => ({ kind: 'step', id: action.id, action })),
        ...stacks.map((group): VisibleNode => ({ kind: 'stack', id: group.id, group })),
    ].sort((a, b) => orderOf(a) - orderOf(b))
}

function edgeLabel(workflow: FlowGraph, edge: HogFlowEdge, collapsed: Collapsed): string | undefined {
    const isPathChoice = outgoingEdges(workflow, edge.from).length > 1
    return isPathChoice && !collapsed.namedElsewhere.has(getEdgeId(edge))
        ? getWorkflowBranchLabel(collapsed.actionsById.get(edge.from), edge)
        : undefined
}

/** Arrows that a collapsed path turns into the same arrow become one, which no step can be inserted into. */
function mergeVisibleEdges(workflow: FlowGraph, collapsed: Collapsed): VisibleEdge[] {
    const shown = (id: string): string => collapsed.stackOf.get(id) ?? id
    const edgesById = new Map<string, VisibleEdge>()
    workflow.edges.forEach((edge) => {
        const source = shown(edge.from)
        const target = shown(edge.to)
        if (source === target) {
            return
        }
        const fromStack = source !== edge.from
        const id = fromStack ? `${source}->${target}` : `${getEdgeId(edge)}${target !== edge.to ? `=>${target}` : ''}`
        const existing = edgesById.get(id)
        if (existing) {
            existing.originalEdgeKeys.push(getEdgeId(edge))
            existing.insertEdge = undefined
            return
        }
        edgesById.set(id, {
            id,
            source,
            target,
            portIndex: 0,
            portCount: 1,
            label: fromStack ? undefined : edgeLabel(workflow, edge, collapsed),
            insertEdge: fromStack || target !== edge.to ? undefined : edge,
            originalEdgeKeys: [getEdgeId(edge)],
        })
    })
    return [...edgesById.values()]
}

/** Each arrow leaves its step from its own port, in path order, so the arrows of a split never cross. */
function assignSourcePorts(workflow: FlowGraph, edges: VisibleEdge[]): VisibleEdge[] {
    const bySource = new Map<string, VisibleEdge[]>()
    edges.forEach((edge) => bySource.set(edge.source, [...(bySource.get(edge.source) ?? []), edge]))
    bySource.forEach((fromSource, sourceId) => {
        const order = outgoingEdges(workflow, sourceId).map(getEdgeId)
        fromSource
            .sort((a, b) => order.indexOf(a.originalEdgeKeys[0]) - order.indexOf(b.originalEdgeKeys[0]))
            .forEach((edge, index) => {
                edge.portIndex = index
                edge.portCount = fromSource.length
            })
    })
    return edges
}

export function computeVisibleGraph(
    workflow: FlowGraph,
    groups: PathGroup[],
    openGroupIds: readonly string[]
): VisibleGraph {
    const stacks = collapsedPathStacks(groups, openGroupIds)
    const frames = openPathFrames(groups, openGroupIds)
    const collapsed: Collapsed = {
        stackOf: new Map(stacks.flatMap((group) => group.memberIds.map((id): [string, string] => [id, group.id]))),
        namedElsewhere: new Set([...stacks, ...frames].map((group) => getEdgeId(group.entryEdge))),
        actionsById: actionsById(workflow),
    }
    return {
        nodes: visibleNodes(workflow, stacks, collapsed),
        edges: assignSourcePorts(workflow, mergeVisibleEdges(workflow, collapsed)),
    }
}

/** The people a step handled. Unknown until the metrics load, so the tile shows no number rather than a wrong one.
 * A workflow with no runs in the window shows no numbers either, so a draft is not covered in zeros. */
export function stepCount(
    metrics: Record<string, HogFlowEditorActionMetrics> | null,
    actionId: string
): number | undefined {
    if (!metrics || Object.keys(metrics).length === 0) {
        return undefined
    }
    const entry = metrics[actionId]
    return entry ? entry.succeeded + entry.failed + entry.filtered : 0
}

const STEP_COUNT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
const STEP_COUNT_METRICS = ['succeeded', 'failed', 'filtered', 'rate_limited', 'triggered']

/** Batch workflows report metrics per run, not per step, so they get no step counts. */
function canCountSteps(workflow: Pick<HogFlow, 'id' | 'trigger'>): boolean {
    return !!workflow.id && workflow.id !== 'new' && workflow.trigger?.type !== 'batch'
}

/** Metrics loaded earlier, or answered late, must not show once the workflow stops qualifying for step counts. */
export function countableStepMetrics(
    workflow: Pick<HogFlow, 'id' | 'trigger'>,
    metrics: Record<string, HogFlowEditorActionMetrics> | null
): Record<string, HogFlowEditorActionMetrics> | null {
    return canCountSteps(workflow) ? metrics : null
}

/** One row per step and metric, plus the trigger and exit rows that have no step. Without a limit the query
 * stops at 100 rows, and a big workflow loses the counts of its last steps. */
function stepCountRowLimit(workflow: Pick<HogFlow, 'actions'>): number {
    return (workflow.actions.length + 1) * STEP_COUNT_METRICS.length
}

export function stepCountsRequest(
    workflow: Pick<HogFlow, 'id' | 'trigger' | 'actions'>,
    now: Date
): AppMetricsTotalsRequest | null {
    if (!canCountSteps(workflow)) {
        return null
    }
    return {
        appSource: 'hog_flow',
        appSourceId: workflow.id,
        dateFrom: new Date(now.getTime() - STEP_COUNT_WINDOW_MS).toISOString(),
        dateTo: now.toISOString(),
        breakdownBy: ['instance_id', 'metric_name'],
        metricName: STEP_COUNT_METRICS,
        limit: stepCountRowLimit(workflow),
    }
}

export interface Point {
    x: number
    y: number
}

export interface Viewport {
    x: number
    y: number
    zoom: number
}

export interface Size {
    width: number
    height: number
}

export const FIT_MARGIN = { side: 24, top: 32, bottom: 96 }
const VIEWPORT_MARGIN = 24

function shiftIntoView(
    offset: number,
    start: number,
    length: number,
    zoom: number,
    extent: number,
    farMargin = VIEWPORT_MARGIN
): number {
    const near = start * zoom + offset
    const far = (start + length) * zoom + offset
    if (near < VIEWPORT_MARGIN) {
        return offset + VIEWPORT_MARGIN - near
    }
    if (far > extent - farMargin) {
        return offset - Math.min(far - (extent - farMargin), near - VIEWPORT_MARGIN)
    }
    return offset
}

export function viewportAfterResize(viewport: Viewport, previous: Size, next: Size, focus?: Point & Size): Viewport {
    const x = viewport.x + (next.width - previous.width) / 2
    const y = viewport.y + (next.height - previous.height) / 2
    if (!focus) {
        return { x, y, zoom: viewport.zoom }
    }
    return {
        x: shiftIntoView(x, focus.x, focus.width, viewport.zoom, next.width),
        y: shiftIntoView(y, focus.y, focus.height, viewport.zoom, next.height, FIT_MARGIN.bottom),
        zoom: viewport.zoom,
    }
}

export function viewportShowing(viewport: Viewport, canvas: Size, focus: Point & Size): Viewport {
    return viewportAfterResize(viewport, canvas, canvas, focus)
}

export const CANVAS_MIN_ZOOM = 0.15

/** The command bar floats over the bottom of the canvas, so the room to show things in ends above it. */
function roomInView(canvas: Size): Size {
    return {
        width: canvas.width - FIT_MARGIN.side * 2,
        height: canvas.height - FIT_MARGIN.top - FIT_MARGIN.bottom,
    }
}

/** Centres a frame in view. Zooms out only when the frame does not fit at the zoom the person chose. */
export function viewportToFit(frame: Point & Size, canvas: Size, zoom: number): Viewport {
    const room = roomInView(canvas)
    const fits = frame.width * zoom <= room.width && frame.height * zoom <= room.height
    const nextZoom = fits
        ? zoom
        : Math.max(CANVAS_MIN_ZOOM, Math.min(room.width / frame.width, room.height / frame.height))
    return {
        x: FIT_MARGIN.side + (room.width - frame.width * nextZoom) / 2 - frame.x * nextZoom,
        y: FIT_MARGIN.top + (room.height - frame.height * nextZoom) / 2 - frame.y * nextZoom,
        zoom: nextZoom,
    }
}

const MIN_READABLE_ZOOM = 0.66
/** How much of a path must show around where its arrow enters, in canvas pixels. */
const ANCHOR_HEAD = 120

/** Where a path sits on the canvas, and where the arrow into it meets it. */
export interface PathPlace extends Point, Size {
    entry: Point
}

interface ScreenBounds {
    left: number
    top: number
    right: number
    bottom: number
}

function roomBounds(canvas: Size): ScreenBounds {
    return {
        left: FIT_MARGIN.side,
        top: FIT_MARGIN.top,
        right: canvas.width - FIT_MARGIN.side,
        bottom: canvas.height - FIT_MARGIN.bottom,
    }
}

const onScreen = (point: Point, viewport: Viewport): Point => ({
    x: viewport.x + point.x * viewport.zoom,
    y: viewport.y + point.y * viewport.zoom,
})

function isOnScreen(box: Point & Size, viewport: Viewport, room: ScreenBounds): boolean {
    const topLeft = onScreen(box, viewport)
    return (
        topLeft.x < room.right &&
        topLeft.x + box.width * viewport.zoom > room.left &&
        topLeft.y < room.bottom &&
        topLeft.y + box.height * viewport.zoom > room.top
    )
}

const clamp = (value: number, low: number, high: number): number => Math.min(Math.max(value, low), Math.max(low, high))

/** How far a place reaches from its entry to each side, in canvas pixels. */
function reach(place: PathPlace): ScreenBounds {
    return {
        left: place.entry.x - place.x,
        top: place.entry.y - place.y,
        right: place.x + place.width - place.entry.x,
        bottom: place.y + place.height - place.entry.y,
    }
}

/** Moves the anchor only as far as needed for the part of the next place around its entry to show. */
function anchorInRoom(anchor: Point, next: PathPlace, zoom: number, room: ScreenBounds): Point {
    const around = reach(next)
    return {
        x: clamp(
            anchor.x,
            room.left + Math.min(around.left, ANCHOR_HEAD) * zoom,
            room.right - Math.min(around.right, ANCHOR_HEAD) * zoom
        ),
        y: clamp(anchor.y, room.top, room.bottom - Math.min(around.bottom, ANCHOR_HEAD) * zoom),
    }
}

function zoomToShowFrom(anchor: Point, next: PathPlace, room: ScreenBounds, zoom: number): number {
    const fitting = Math.min(
        (room.right - room.left) / Math.max(next.width, 1),
        (room.bottom - anchor.y) / Math.max(reach(next).bottom, 1)
    )
    return fitting >= zoom ? zoom : Math.max(fitting, Math.min(zoom, MIN_READABLE_ZOOM))
}

/** Slides the view sideways only as far as needed for a box as wide as the canvas or narrower to show whole. */
function slideIntoRoom(x: number, box: Point & Size, zoom: number, room: ScreenBounds): number {
    const left = x + box.x * zoom
    const right = left + box.width * zoom
    if (right - left > room.right - room.left) {
        return x
    }
    return x + Math.max(0, room.left - left) - Math.max(0, right - room.right)
}

/**
 * Keeps a path where the person saw it as it opens or collapses: the arrow into the path stays where it was on screen,
 * and everything else moves around it. A frame that would open past the side of the canvas slides in just enough to
 * show whole. Zooms out only as far as the new place needs, never below a readable zoom, and never zooms in. A path
 * opened from a stack out of view is centred instead.
 */
export function viewportAnchoredOn(previous: PathPlace, next: PathPlace, viewport: Viewport, canvas: Size): Viewport {
    const room = roomBounds(canvas)
    if (!isOnScreen(previous, viewport, room)) {
        return viewportToFit(next, canvas, viewport.zoom)
    }
    const anchor = anchorInRoom(onScreen(previous.entry, viewport), next, viewport.zoom, room)
    const zoom = zoomToShowFrom(anchor, next, room, viewport.zoom)
    const x = slideIntoRoom(anchor.x - next.entry.x * zoom, next, zoom, room)
    return { x, y: anchor.y - next.entry.y * zoom, zoom }
}

/**
 * Fits the workflow, but never shrinks it below a readable zoom: people pan to see the rest of a big one. A workflow
 * too wide to fit starts at its trigger, in the middle of the canvas, since it usually sits above the middle of its
 * paths and the left edge would show only empty canvas.
 */
export function readableFitViewport(bounds: Point & Size, canvas: Size, trigger: Point): Viewport {
    const width = bounds.width + FIT_MARGIN.side * 2
    const height = bounds.height + FIT_MARGIN.top + FIT_MARGIN.bottom
    const zoom = Math.min(1, Math.max(MIN_READABLE_ZOOM, Math.min(canvas.width / width, canvas.height / height)))
    const room = roomBounds(canvas)
    const fitsWidth = bounds.width * zoom <= room.right - room.left
    const x = fitsWidth
        ? (canvas.width - bounds.width * zoom) / 2 - bounds.x * zoom
        : clamp(
              canvas.width / 2 - trigger.x * zoom,
              room.right - (bounds.x + bounds.width) * zoom,
              room.left - bounds.x * zoom
          )
    return { x, y: FIT_MARGIN.top - bounds.y * zoom, zoom }
}

export interface MiniFlowLayout {
    nodes: { actionId: string; x: number; y: number; layer: number }[]
    edges: { from: Point; to: Point }[]
    width: number
    height: number
}

export function layoutMiniFlow(
    workflow: FlowGraph,
    memberIds: string[],
    spacing: { tile: number; gapX: number; gapY: number }
): MiniFlowLayout {
    const rank = new Map(memberIds.map((id, index) => [id, index]))
    const inner = memberIds.flatMap((id) => outgoingEdges(workflow, id).filter((edge) => rank.has(edge.to)))
    // Members come in flow order, so one pass over the edges that point forward places every step after the ones before it.
    const layer = new Map(memberIds.map((id) => [id, 0]))
    inner
        .filter((edge) => (rank.get(edge.to) as number) > (rank.get(edge.from) as number))
        .forEach((edge) => layer.set(edge.to, Math.max(layer.get(edge.to) ?? 0, (layer.get(edge.from) ?? 0) + 1)))
    const columns: string[][] = []
    memberIds.forEach((id) => (columns[layer.get(id) ?? 0] ??= []).push(id))
    const tallest = Math.max(...columns.map((column) => column?.length ?? 0))
    const nodes = columns.flatMap((column, index) =>
        (column ?? []).map((actionId, row) => ({
            actionId,
            layer: index,
            x: index * (spacing.tile + spacing.gapX),
            y: (row - (column.length - 1) / 2 + (tallest - 1) / 2) * spacing.gapY,
        }))
    )
    const at = new Map(nodes.map((node) => [node.actionId, node]))
    const center = spacing.tile / 2
    return {
        nodes,
        edges: inner.map((edge) => {
            const from = at.get(edge.from) as Point
            const to = at.get(edge.to) as Point
            return { from: { x: from.x + spacing.tile, y: from.y + center }, to: { x: to.x, y: to.y + center } }
        }),
        width: columns.length * (spacing.tile + spacing.gapX) - spacing.gapX,
        height: (tallest - 1) * spacing.gapY + spacing.tile,
    }
}

function isInTriangle(point: Point, a: Point, b: Point, c: Point): boolean {
    const side = (p1: Point, p2: Point, p3: Point): number =>
        (p1.x - p3.x) * (p2.y - p3.y) - (p2.x - p3.x) * (p1.y - p3.y)
    const sides = [side(point, a, b), side(point, b, c), side(point, c, a)]
    return !(sides.some((value) => value < 0) && sides.some((value) => value > 0))
}

/**
 * True while the pointer stays inside the triangle between where it left a step and the top edge of
 * that step's open preview. Steps it crosses on the way there must not take the hover away.
 */
export function isHeadingToRect(
    pointer: Point,
    apex: Point,
    rect: { left: number; right: number; top: number },
    slack: number
): boolean {
    return isInTriangle(pointer, apex, { x: rect.left - slack, y: rect.top }, { x: rect.right + slack, y: rect.top })
}

export interface PaletteSection {
    title: string
    steps: CreateActionType[]
}

export interface PaletteCommand {
    id: string
    label: string
    hint?: string
}

export type PaletteItem<Command extends PaletteCommand = PaletteCommand> =
    | { kind: 'step'; key: string; section: string; label: string; description?: string; step: CreateActionType }
    | { kind: 'command'; key: string; section: string; label: string; description?: string; command: Command }

/** Two destinations can share a name, so the key also carries the template the step runs. */
function paletteStepKey(section: string, step: CreateActionType): string {
    const templateId = 'template_id' in step.config ? step.config.template_id : undefined
    return `${section}:${step.type}:${templateId ?? ''}:${step.name}`
}

const matches = (query: string, texts: (string | undefined)[]): boolean =>
    !query || texts.some((text) => text?.toLowerCase().includes(query.toLowerCase()))

// With an empty search, commands lead. Once someone types, they are probably after a step, so steps lead.
export function filterPaletteItems<Command extends PaletteCommand>(
    query: string,
    sections: PaletteSection[],
    commands: Command[]
): PaletteItem<Command>[] {
    const trimmed = query.trim()
    const steps = sections.flatMap(({ title, steps }) =>
        steps
            .filter((step) => matches(trimmed, [step.name, step.description, title]))
            .map(
                (step): PaletteItem<Command> => ({
                    kind: 'step',
                    key: paletteStepKey(title, step),
                    section: title,
                    label: step.name,
                    description: step.description,
                    step,
                })
            )
    )
    const commandItems = commands
        .filter((command) => matches(trimmed, [command.label, command.hint]))
        .map(
            (command): PaletteItem<Command> => ({
                kind: 'command',
                key: command.id,
                section: 'Commands',
                label: command.label,
                description: command.hint,
                command,
            })
        )
    return trimmed ? [...steps, ...commandItems] : [...commandItems, ...steps]
}

export interface CanvasMotion {
    kind: 'expand' | 'collapse' | 'settle'
    groupId: string
    origin: Point
}

export interface NodeMotion {
    type: 'enter' | 'leave' | 'pop' | 'fade-in' | 'fade-out'
    dx: number
    dy: number
}

function movingPathGroup(motion: CanvasMotion, groups: PathGroup[]): PathGroup | undefined {
    return groups.find((candidate) => candidate.id === motion.groupId)
}

/** Steps fly out of the stack's tile when a path opens, and back into it when the path collapses. */
function motionTowardStack(
    motion: CanvasMotion,
    box: { x: number; y: number; width: number; height: number }
): NodeMotion {
    return {
        type: motion.kind === 'expand' ? 'enter' : 'leave',
        dx: motion.origin.x - (box.x + box.width / 2),
        dy: motion.origin.y - (box.y + box.height / 2),
    }
}

export function nodeMotion(
    motion: CanvasMotion | null,
    node: VisibleNode,
    groups: PathGroup[],
    box: { x: number; y: number; width: number; height: number } | undefined
): NodeMotion | undefined {
    if (!motion || !box) {
        return undefined
    }
    if (motion.kind === 'settle') {
        return node.id === motion.groupId ? { type: 'pop', dx: 0, dy: 0 } : undefined
    }
    const group = movingPathGroup(motion, groups)
    return group && isInPathGroup(group, node) ? motionTowardStack(motion, box) : undefined
}

export function frameMotion(
    motion: CanvasMotion | null,
    group: PathGroup,
    groups: PathGroup[]
): NodeMotion | undefined {
    if (!motion || motion.kind === 'settle') {
        return undefined
    }
    const isMoving =
        group.id === motion.groupId || ancestorsOf(groups, group).some((other) => other.id === motion.groupId)
    return isMoving ? { type: motion.kind === 'expand' ? 'fade-in' : 'fade-out', dx: 0, dy: 0 } : undefined
}
