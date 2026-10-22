import { compareRowKey } from 'products/tracing/frontend/compareUtils'
import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'

// A wide fan-out shows this many children until the person asks for the rest.
export const TRACE_DIALOG_CHILD_LIMIT = 10
export const TRACE_DIALOG_MIN_CHAIN = 3

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
          }
        /** The first span stands for the chain in selection and the inspector. */
        | { kind: 'chain'; nodes: SpanNode[] }
        /** `hidden` holds the children past the cap, in start order. */
        | { kind: 'more'; parent: SpanNode; hiddenCount: number; hidden: SpanNode[] }
    )

export function rowSpanNode(row: TraceDialogRow): SpanNode | null {
    return row.kind === 'span' ? row.node : row.kind === 'chain' ? row.nodes[0] : null
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
    /** The span a log came from. It stays on screen: past the child cap, and outside folded chains. */
    pinned: SpanNode | null
}

/** Chains fold so long call chains don't push the tree off the right edge. */
export function buildTraceDialogRows(
    roots: SpanNode[],
    { collapsedSpanIds, fullChildListSpanIds, openChainIds, pinned }: TraceDialogRowOptions
): TraceDialogRow[] {
    const pinnedPath = new Set<SpanNode>()
    for (let node = pinned; node; node = node.parent) {
        pinnedPath.add(node)
    }

    type Pending = { node: SpanNode; depth: number; isLast: boolean; parentRow: TraceDialogRow | null }
    const rows: TraceDialogRow[] = []
    // Spans that must not start a fold: members of an opened chain, and spans at or above the pinned
    // span in a run. Marking them keeps a deep pinned chain to one scan instead of one per member.
    const noFold = new Set<SpanNode>()
    const stack: (Pending | TraceDialogRow)[] = []
    const isOnPinnedPath = (node: SpanNode): boolean => pinnedPath.has(node)
    const pushChildren = (children: SpanNode[], owner: SpanNode, depth: number, parentRow: TraceDialogRow): void => {
        const sorted = byStart(children)
        const showsAll = fullChildListSpanIds.has(owner.span.span_id)
        const isShown = (_child: SpanNode, i: number): boolean => showsAll || !childCapHides(sorted, i, isOnPinnedPath)
        const shown = sorted.filter(isShown)
        const hidden = sorted.filter((child, i) => !isShown(child, i))
        const hiddenCount = hidden.length
        const next: (Pending | TraceDialogRow)[] = shown.map((child, i) => ({
            node: child,
            depth,
            isLast: hiddenCount === 0 && i === shown.length - 1,
            parentRow,
        }))
        if (hiddenCount > 0) {
            next.push({ kind: 'more', parent: owner, hiddenCount, hidden, depth, isLast: true, parentRow })
        }
        for (let i = next.length - 1; i >= 0; i--) {
            stack.push(next[i])
        }
    }

    const sortedRoots = byStart(roots)
    for (let i = sortedRoots.length - 1; i >= 0; i--) {
        stack.push({ node: sortedRoots[i], depth: 0, isLast: i === sortedRoots.length - 1, parentRow: null })
    }
    while (stack.length > 0) {
        const item = stack.pop()!
        if ('kind' in item) {
            rows.push(item)
            continue
        }
        const { node, depth, isLast, parentRow } = item
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
        }
        rows.push(row)
        if (node.children.length > 0 && !collapsedSpanIds.has(node.span.span_id)) {
            pushChildren(node.children, node, depth + 1, row)
        }
    }
    return rows
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
 * members of a folded chain, the spans under a collapsed span, and the children past the cap with every span
 * under them. Nothing else on screen shows those spans, so a hidden match keeps its row bright.
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
        if (row.kind === 'more') {
            return row.hidden.some((child) => subtreeMarks.has(child))
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
}

/** `node` and the spans above it, root first. */
function pathFromRoot(node: SpanNode): SpanNode[] {
    const path: SpanNode[] = []
    for (let ancestor: SpanNode | null = node; ancestor; ancestor = ancestor.parent) {
        path.push(ancestor)
    }
    return path.reverse()
}

/** The ids to open so that `target` gets a row of its own, or heads a folded chain, which shows its name. */
export function revealSpanInRows(
    roots: SpanNode[],
    target: SpanNode,
    options: TraceDialogRowOptions
): TraceDialogReveal {
    const path = pathFromRoot(target)
    const pinnedPath = new Set(options.pinned ? pathFromRoot(options.pinned) : [])
    const isOnPinnedPath = (node: SpanNode): boolean => pinnedPath.has(node)
    const collapsedSpanIds = path
        .filter((node) => node !== target && options.collapsedSpanIds.has(node.span.span_id))
        .map((node) => node.span.span_id)
    // With the collapsed ancestors open, only the child caps along the path can still hide the target. A folded
    // chain holds spans with one child each, so no cap sits inside one. One walk down the path finds every cap.
    const fullChildListSpanIds: string[] = []
    for (const node of path) {
        if (!node.parent || options.fullChildListSpanIds.has(node.parent.span.span_id)) {
            continue
        }
        const siblings = byStart(node.parent.children)
        if (childCapHides(siblings, siblings.indexOf(node), isOnPinnedPath)) {
            fullChildListSpanIds.push(node.parent.span.span_id)
        }
    }
    // The row builder decides which runs fold, so this asks it rather than repeating its rules.
    const collapsed = new Set(options.collapsedSpanIds)
    collapsedSpanIds.forEach((spanId) => collapsed.delete(spanId))
    const rows = buildTraceDialogRows(roots, {
        ...options,
        collapsedSpanIds: collapsed,
        fullChildListSpanIds: new Set([...options.fullChildListSpanIds, ...fullChildListSpanIds]),
    })
    const chain = rows.find((row) => row.kind === 'chain' && row.nodes.includes(target))
    const chainIds = chain?.kind === 'chain' && chain.nodes[0] !== target ? [chain.nodes[0].span.span_id] : []
    return { collapsedSpanIds, fullChildListSpanIds, chainIds }
}
