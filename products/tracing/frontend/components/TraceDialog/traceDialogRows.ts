import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'

// A wide fan-out shows this many children until the person asks for the rest.
export const TRACE_DIALOG_CHILD_LIMIT = 10
// A run of this many spans that each have one child folds into one row.
export const TRACE_DIALOG_MIN_CHAIN = 3

interface TraceDialogRowBase {
    depth: number
    /** The last row under its parent, so its connector ends at this row. */
    isLast: boolean
    /** The row this one hangs under. Connectors walk it up, so they are derived only for rows on screen. */
    parentRow: TraceDialogRow | null
}

export type TraceDialogRow = TraceDialogRowBase &
    (
        | {
              kind: 'span'
              node: SpanNode
              /** Set on the first span of a chain the person opened, so the row can fold it again. */
              openChainLength?: number
          }
        /** A folded run of single-child spans. Its first span stands for it in selection and the inspector. */
        | { kind: 'chain'; nodes: SpanNode[] }
        | { kind: 'more'; parent: SpanNode; hiddenCount: number }
    )

/** The span a row selects: the span itself, or the first span of a folded chain. */
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

/** The run of single-child spans that starts at `first`, ending before the first span that branches. */
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

/**
 * The rows the span list shows, depth first in start order. A collapsed span hides its subtree. A span
 * with more than TRACE_DIALOG_CHILD_LIMIT children shows the first ones and a "more" row, unless its
 * children are shown in full. A run of TRACE_DIALOG_MIN_CHAIN or more single-child spans folds into one
 * row until the person opens it, which keeps long call chains from pushing the tree off the right edge.
 */
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
    // Spans inside a chain the person opened, which must not fold again from their own position.
    const openedMembers = new Set<SpanNode>()
    const stack: (Pending | TraceDialogRow)[] = []
    const pushChildren = (children: SpanNode[], owner: SpanNode, depth: number, parentRow: TraceDialogRow): void => {
        let shown = byStart(children)
        if (shown.length > TRACE_DIALOG_CHILD_LIMIT && !fullChildListSpanIds.has(owner.span.span_id)) {
            shown = shown.filter((child, i) => i < TRACE_DIALOG_CHILD_LIMIT || pinnedPath.has(child))
        }
        const hiddenCount = children.length - shown.length
        const next: (Pending | TraceDialogRow)[] = shown.map((child, i) => ({
            node: child,
            depth,
            isLast: hiddenCount === 0 && i === shown.length - 1,
            parentRow,
        }))
        if (hiddenCount > 0) {
            next.push({ kind: 'more', parent: owner, hiddenCount, depth, isLast: true, parentRow })
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
            node.parent?.children.length === 1 && !openedMembers.has(node) ? singleChildRun(node, collapsedSpanIds) : []
        const foldable = run.length >= TRACE_DIALOG_MIN_CHAIN && !run.some((member) => pinnedPath.has(member))
        if (foldable && !openChainIds.has(node.span.span_id)) {
            const chainRow: TraceDialogRow = { kind: 'chain', nodes: run, depth, isLast, parentRow }
            rows.push(chainRow)
            const after = run[run.length - 1].children[0]
            stack.push({ node: after, depth: depth + 1, isLast: true, parentRow: chainRow })
            continue
        }
        if (foldable) {
            run.forEach((member) => openedMembers.add(member))
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

/** Whether each ancestor level, root side first, still has rows below, so the tree draws its lines. */
export function rowConnectorLines(row: TraceDialogRow): boolean[] {
    const lines: boolean[] = []
    for (let ancestor = row.parentRow; ancestor && ancestor.depth > 0; ancestor = ancestor.parentRow) {
        lines.push(!ancestor.isLast)
    }
    return lines.reverse()
}
