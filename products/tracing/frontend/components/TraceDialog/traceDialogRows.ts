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
        | { kind: 'more'; parent: SpanNode; hiddenCount: number }
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
