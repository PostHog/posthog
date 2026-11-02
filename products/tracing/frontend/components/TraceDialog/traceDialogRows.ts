import { compareRowKey } from 'products/tracing/frontend/compareUtils'
import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'

// A wide fan-out shows this many children until the person asks for the rest.
export const TRACE_DIALOG_CHILD_LIMIT = 10
export const TRACE_DIALOG_MIN_CHAIN = 3
export const TRACE_DIALOG_MIN_RUN = 3

interface TraceDialogRowBase {
    depth: number
    isLast: boolean
    /** Connectors walk this up, so they are derived only for rows on screen. */
    parentRow: TraceDialogRow | null
}

export type TraceDialogRow = TraceDialogRowBase &
    (
        | {
              kind: 'span'
              node: SpanNode
              openChainLength?: number
              /** Set on the first span of an opened run that can fold again. */
              openRunLength?: number
              /** Set on every span of an opened run that can fold again: the run's first span, which stays listed. */
              openRunStart?: SpanNode
          }
        /** The first span stands for the chain in selection and the inspector. */
        | { kind: 'chain'; nodes: SpanNode[] }
        /**
         * Adjacent siblings of one operation, in start order. `key` is their `compareRowKey`. The first span
         * stands for the run in selection and the inspector, so J and K stop on it without opening it.
         */
        | { kind: 'run'; nodes: SpanNode[]; key: string }
        /** `hidden` holds the children past the cap, in start order. */
        | { kind: 'more'; parent: SpanNode; hiddenCount: number; hidden: SpanNode[] }
        /** Ends a full child list that is longer than the cap, so the person can shorten it again. */
        | { kind: 'fewer'; parent: SpanNode }
    )

export function rowSpanNode(row: TraceDialogRow): SpanNode | null {
    return row.kind === 'span' ? row.node : row.kind === 'chain' || row.kind === 'run' ? row.nodes[0] : null
}

function byStart(nodes: SpanNode[]): SpanNode[] {
    return [...nodes].sort((a, b) => parseTimestampUs(a.span.timestamp) - parseTimestampUs(b.span.timestamp))
}

/** How many spans sit under each span, keyed by span id. One pass, so deep traces stay off the call stack. */
export function countDescendantsById(roots: SpanNode[]): Map<string, number> {
    const order: SpanNode[] = []
    const stack = [...roots]
    while (stack.length > 0) {
        const node = stack.pop()!
        order.push(node)
        stack.push(...node.children)
    }
    const counts = new Map<string, number>()
    // Children come after their parent in `order`, so walking it backwards totals each child first.
    for (let i = order.length - 1; i >= 0; i--) {
        const node = order[i]
        counts.set(
            node.span.span_id,
            node.children.reduce((total, child) => total + 1 + (counts.get(child.span.span_id) ?? 0), 0)
        )
    }
    return counts
}

/**
 * Whether a parent's child cap hides the sibling at `index`. `siblings` are in start order. A sibling on the path to
 * the pinned span always shows.
 */
function childCapHides<T>(siblings: T[], index: number, isPinned: (sibling: T) => boolean): boolean {
    return siblings.length > TRACE_DIALOG_CHILD_LIMIT && index >= TRACE_DIALOG_CHILD_LIMIT && !isPinned(siblings[index])
}

function singleChildRun(first: SpanNode, collapsedSpanIds: Set<string>): SpanNode[] {
    const run: SpanNode[] = []
    let node: SpanNode | undefined = first
    while (node && node.children.length === 1 && !collapsedSpanIds.has(node.span.span_id)) {
        run.push(node)
        node = node.children[0]
    }
    return run
}

export interface TraceDialogRowOptions {
    collapsedSpanIds: Set<string>
    fullChildListSpanIds: Set<string>
    openChainIds: Set<string>
    /** False gives every span a row of its own and makes the child cap count spans. */
    foldRuns: boolean
    /** Runs fold by default, so this holds the opened ones, by the id of their first span. */
    openRunIds: Set<string>
    /** The span a log came from. It stays on screen: past the child cap, and outside folded chains and runs. */
    pinned: SpanNode | null
}

/** Siblings in start order, split where the operation changes. A group of one operation can fold into a run. */
function operationGroups(sorted: SpanNode[]): SpanNode[][] {
    const groups: SpanNode[][] = []
    let lastKey: string | null = null
    for (const node of sorted) {
        // Placeholders all share one label, but each one stands for a different absent parent, so they never fold.
        const key = node.isMissingParent ? null : compareRowKey(node.span)
        if (key !== null && key === lastKey) {
            groups[groups.length - 1].push(node)
        } else {
            groups.push([node])
        }
        lastKey = key
    }
    return groups
}

/**
 * The siblings that count as one item toward the child cap: a span, a folded run, or an opened run, which
 * lists all of its spans. `foldable` is false for a run that the pin holds open, because a fold would change
 * nothing.
 */
type Unit = { node: SpanNode } | { run: SpanNode[] } | { openRun: SpanNode[]; foldable: boolean }

function unitSpans(unit: Unit): SpanNode[] {
    return 'node' in unit ? [unit.node] : 'run' in unit ? unit.run : unit.openRun
}

// A run with the pinned span in it or under it never folds, so a folded run is never on the pinned path.
function unitOnPinnedPath(unit: Unit, pinnedPath: Set<SpanNode>): boolean {
    return !('run' in unit) && unitSpans(unit).some((node) => pinnedPath.has(node))
}

interface SiblingUnitOptions {
    foldRuns: boolean
    openRunIds: Set<string>
    pinnedPath: Set<SpanNode>
}

/** Siblings in start order, as items of the child cap. The row builder and the reveal both use it, so they agree. */
function siblingUnits(siblings: SpanNode[], { foldRuns, openRunIds, pinnedPath }: SiblingUnitOptions): Unit[] {
    if (!foldRuns) {
        return byStart(siblings).map((node) => ({ node }))
    }
    return operationGroups(byStart(siblings)).flatMap((group): Unit[] => {
        if (group.length < TRACE_DIALOG_MIN_RUN) {
            return group.map((node) => ({ node }))
        }
        if (group.some((member) => pinnedPath.has(member))) {
            return [{ openRun: group, foldable: false }]
        }
        return openRunIds.has(group[0].span.span_id) ? [{ openRun: group, foldable: true }] : [{ run: group }]
    })
}

/**
 * Chains fold so long call chains don't push the tree off the right edge. Runs of one operation under one parent
 * fold so a loop of identical calls doesn't push the rest of the trace out of view.
 */
export function buildTraceDialogRows(
    roots: SpanNode[],
    { collapsedSpanIds, fullChildListSpanIds, openChainIds, foldRuns, openRunIds, pinned }: TraceDialogRowOptions
): TraceDialogRow[] {
    const pinnedPath = new Set<SpanNode>()
    for (let node = pinned; node; node = node.parent) {
        pinnedPath.add(node)
    }
    const unitOptions: SiblingUnitOptions = { foldRuns, openRunIds, pinnedPath }

    type Pending = {
        node: SpanNode
        depth: number
        isLast: boolean
        parentRow: TraceDialogRow | null
        openRunLength?: number
        openRunStart?: SpanNode
    }
    const rows: TraceDialogRow[] = []
    // Spans that must not start a fold: members of an opened chain, and spans at or above the pinned
    // span in a run. Marking them keeps a deep pinned chain to one scan instead of one per member.
    const noFold = new Set<SpanNode>()
    const stack: (Pending | TraceDialogRow)[] = []
    const unitRows = (
        units: Unit[],
        depth: number,
        parentRow: TraceDialogRow | null,
        hasTrailingRow: boolean
    ): (Pending | TraceDialogRow)[] => {
        const entries = units.flatMap((unit): (Pending | TraceDialogRow)[] => {
            if ('run' in unit) {
                const key = compareRowKey(unit.run[0].span)
                return [{ kind: 'run', nodes: unit.run, key, depth, isLast: false, parentRow }]
            }
            if ('node' in unit) {
                return [{ node: unit.node, depth, isLast: false, parentRow }]
            }
            return unit.openRun.map((node, i) => ({
                node,
                depth,
                isLast: false,
                parentRow,
                ...(unit.foldable && i === 0 ? { openRunLength: unit.openRun.length } : {}),
                ...(unit.foldable ? { openRunStart: unit.openRun[0] } : {}),
            }))
        })
        if (!hasTrailingRow && entries.length > 0) {
            entries[entries.length - 1].isLast = true
        }
        return entries
    }
    const isUnitOnPinnedPath = (unit: Unit): boolean => unitOnPinnedPath(unit, pinnedPath)
    // The cap counts items after the fold, so a run of thousands of spans takes one item of the cap, folded
    // or opened. The list is virtualized, so an opened run can list all of its spans.
    const pushChildren = (children: SpanNode[], owner: SpanNode, depth: number, parentRow: TraceDialogRow): void => {
        const units = siblingUnits(children, unitOptions)
        const showsAll = fullChildListSpanIds.has(owner.span.span_id)
        const isShown = (_unit: Unit, i: number): boolean => showsAll || !childCapHides(units, i, isUnitOnPinnedPath)
        const shown = units.filter(isShown)
        const hidden = units.filter((unit, i) => !isShown(unit, i)).flatMap(unitSpans)
        const hiddenCount = hidden.length
        // A full child list that the cap would shorten ends with a row that shortens it again.
        const showsFewerRow = showsAll && units.length > TRACE_DIALOG_CHILD_LIMIT
        const next = unitRows(shown, depth, parentRow, hiddenCount > 0 || showsFewerRow)
        if (hiddenCount > 0) {
            next.push({ kind: 'more', parent: owner, hiddenCount, hidden, depth, isLast: true, parentRow })
        } else if (showsFewerRow) {
            next.push({ kind: 'fewer', parent: owner, depth, isLast: true, parentRow })
        }
        for (let i = next.length - 1; i >= 0; i--) {
            stack.push(next[i])
        }
    }

    const rootRows = unitRows(siblingUnits(roots, unitOptions), 0, null, false)
    for (let i = rootRows.length - 1; i >= 0; i--) {
        stack.push(rootRows[i])
    }
    while (stack.length > 0) {
        const item = stack.pop()!
        if ('kind' in item) {
            rows.push(item)
            continue
        }
        const { node, depth, isLast, parentRow, openRunLength, openRunStart } = item
        const run =
            node.parent?.children.length === 1 && !noFold.has(node) ? singleChildRun(node, collapsedSpanIds) : []
        const pinnedAt = run.findLastIndex((member) => pinnedPath.has(member))
        // Spans below the pinned one can still fold, so only the part down to it is ruled out.
        run.slice(0, pinnedAt + 1).forEach((member) => noFold.add(member))
        const foldable = run.length >= TRACE_DIALOG_MIN_CHAIN && pinnedAt < 0
        if (foldable && !openChainIds.has(node.span.span_id)) {
            const chainRow: TraceDialogRow = { kind: 'chain', nodes: run, depth, isLast, parentRow }
            rows.push(chainRow)
            const after = run[run.length - 1].children[0]
            stack.push({ node: after, depth: depth + 1, isLast: true, parentRow: chainRow })
            continue
        }
        if (foldable) {
            run.forEach((member) => noFold.add(member))
        }
        const row: TraceDialogRow = {
            kind: 'span',
            node,
            depth,
            isLast,
            parentRow,
            ...(foldable ? { openChainLength: run.length } : {}),
            ...(openRunLength ? { openRunLength } : {}),
            ...(openRunStart ? { openRunStart } : {}),
        }
        rows.push(row)
        if (node.children.length > 0 && !collapsedSpanIds.has(node.span.span_id)) {
            pushChildren(node.children, node, depth + 1, row)
        }
    }
    return rows
}

export interface TraceDialogRunSummary {
    startUs: number
    endUs: number
    totalDurationNano: number
    /** The run's own spans with an error status. */
    errorCount: number
    /** The spans under the run's spans with an error status. The folded run hides them, so its row reports them. */
    nestedErrorCount: number
}

export function summarizeRun(nodes: SpanNode[]): TraceDialogRunSummary {
    let startUs = Infinity
    let endUs = -Infinity
    let totalDurationNano = 0
    let errorCount = 0
    for (const { span } of nodes) {
        const spanStartUs = parseTimestampUs(span.timestamp)
        startUs = Math.min(startUs, spanStartUs)
        // An earlier span can outlast a later one, so the run ends at the latest end and not at the last span's end.
        endUs = Math.max(endUs, spanStartUs + span.duration_nano / 1_000)
        totalDurationNano += span.duration_nano
        errorCount += span.status_code === 2 ? 1 : 0
    }
    let nestedErrorCount = 0
    // A stack and not recursion, so a deep subtree under the run stays off the call stack.
    const stack = nodes.flatMap((node) => node.children)
    while (stack.length > 0) {
        const node = stack.pop()!
        nestedErrorCount += node.span.status_code === 2 ? 1 : 0
        stack.push(...node.children)
    }
    return { startUs, endUs, totalDurationNano, errorCount, nestedErrorCount }
}

export function rowConnectorLines(row: TraceDialogRow): boolean[] {
    const lines: boolean[] = []
    for (let ancestor = row.parentRow; ancestor && ancestor.depth > 0; ancestor = ancestor.parentRow) {
        lines.push(!ancestor.isLast)
    }
    return lines.reverse()
}

/** The spans that are of the operation (`compareRowKey`) or have one under them. One pass from the leaves up. */
export function markOperationSubtrees(roots: SpanNode[], operationKey: string): Set<SpanNode> {
    const order: SpanNode[] = []
    const stack = [...roots]
    while (stack.length > 0) {
        const node = stack.pop()!
        order.push(node)
        stack.push(...node.children)
    }
    const marked = new Set<SpanNode>()
    // Children come after their parent in `order`, so walking it backwards marks each child first.
    for (let i = order.length - 1; i >= 0; i--) {
        const node = order[i]
        if (compareRowKey(node.span) === operationKey || node.children.some((child) => marked.has(child))) {
            marked.add(node)
        }
    }
    return marked
}

/**
 * Which rows stand for a span of the operation. A row stands for its own span and for every span it hides: the
 * members of a folded chain, the members of a folded run with every span under them, the spans under a collapsed
 * span, and the children past the cap with every span under them. Nothing else on screen shows those spans, so a
 * hidden match keeps its row bright. The row that shortens a full child list stands for no span.
 */
export function operationRowMatches(
    rows: TraceDialogRow[],
    operationKey: string,
    subtreeMarks: Set<SpanNode>,
    collapsedSpanIds: Set<string>
): boolean[] {
    return rows.map((row) => {
        if (row.kind === 'chain') {
            return row.nodes.some((node) => compareRowKey(node.span) === operationKey)
        }
        if (row.kind === 'run') {
            return row.key === operationKey || row.nodes.some((node) => subtreeMarks.has(node))
        }
        if (row.kind === 'more') {
            return row.hidden.some((child) => subtreeMarks.has(child))
        }
        if (row.kind === 'fewer') {
            return false
        }
        return collapsedSpanIds.has(row.node.span.span_id)
            ? subtreeMarks.has(row.node)
            : compareRowKey(row.node.span) === operationKey
    })
}

/** The first span of the operation in the order the fully open tree lists spans: depth first, siblings by start. */
export function firstOperationSpan(roots: SpanNode[], operationKey: string): SpanNode | null {
    const stack = byStart(roots).reverse()
    while (stack.length > 0) {
        const node = stack.pop()!
        if (compareRowKey(node.span) === operationKey) {
            return node
        }
        stack.push(...byStart(node.children).reverse())
    }
    return null
}

/** What hides a span from the rows, as the ids each `traceViewLogic` action opens. */
export interface TraceDialogReveal {
    /** Collapsed ancestors, for `toggleSpanCollapsed`. */
    collapsedSpanIds: string[]
    /** Ancestors whose child cap hides the path to the span, for `showAllChildren`. */
    fullChildListSpanIds: string[]
    /** The first span of the folded chain that hides the span, for `toggleChain`. */
    chainIds: string[]
    /** The first span of each folded run that hides the span, outermost first, for `toggleRun`. */
    runIds: string[]
}

/** `node` and the spans above it, root first. */
function pathFromRoot(node: SpanNode): SpanNode[] {
    const path: SpanNode[] = []
    for (let ancestor: SpanNode | null = node; ancestor; ancestor = ancestor.parent) {
        path.push(ancestor)
    }
    return path.reverse()
}

/**
 * The ids to open so that `target` gets a row of its own, or heads a folded chain or run, which shows its name.
 */
export function revealSpanInRows(
    roots: SpanNode[],
    target: SpanNode,
    options: TraceDialogRowOptions
): TraceDialogReveal {
    const path = pathFromRoot(target)
    const pinnedPath = new Set(options.pinned ? pathFromRoot(options.pinned) : [])
    const unitOptions: SiblingUnitOptions = { foldRuns: options.foldRuns, openRunIds: options.openRunIds, pinnedPath }
    const isUnitOnPinnedPath = (unit: Unit): boolean => unitOnPinnedPath(unit, pinnedPath)
    const collapsedSpanIds = path
        .filter((node) => node !== target && options.collapsedSpanIds.has(node.span.span_id))
        .map((node) => node.span.span_id)
    // With the collapsed ancestors open, only the child caps and folded runs along the path can still hide the
    // target. A folded chain holds spans with one child each, so no cap or run sits inside one. A level's cap and
    // runs depend only on its own child list, and a folded run counts as one item of the cap like an opened one,
    // so one walk down the path finds every cap and run, outermost first.
    const fullChildListSpanIds: string[] = []
    const runIds: string[] = []
    for (const node of path) {
        const units = siblingUnits(node.parent ? node.parent.children : roots, unitOptions)
        const index = units.findIndex((unit) => unitSpans(unit).includes(node))
        const unit = units[index]
        // Roots have no child cap.
        if (
            node.parent &&
            !options.fullChildListSpanIds.has(node.parent.span.span_id) &&
            childCapHides(units, index, isUnitOnPinnedPath)
        ) {
            fullChildListSpanIds.push(node.parent.span.span_id)
        }
        // A folded run stands for its first span, so the target can head a run that stays folded.
        if ('run' in unit && unit.run[0] !== target) {
            runIds.push(unit.run[0].span.span_id)
        }
    }
    // The row builder decides which chains fold, so this asks it rather than repeating its rules.
    const collapsed = new Set(options.collapsedSpanIds)
    collapsedSpanIds.forEach((spanId) => collapsed.delete(spanId))
    const rows = buildTraceDialogRows(roots, {
        ...options,
        collapsedSpanIds: collapsed,
        fullChildListSpanIds: new Set([...options.fullChildListSpanIds, ...fullChildListSpanIds]),
        openRunIds: new Set([...options.openRunIds, ...runIds]),
    })
    const chain = rows.find((row) => row.kind === 'chain' && row.nodes.includes(target))
    const chainIds = chain?.kind === 'chain' && chain.nodes[0] !== target ? [chain.nodes[0].span.span_id] : []
    return { collapsedSpanIds, fullChildListSpanIds, chainIds, runIds }
}
