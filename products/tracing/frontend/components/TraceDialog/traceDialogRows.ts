import { parseTimestampUs, type SpanNode } from 'products/tracing/frontend/spanTree'

// A wide fan-out shows this many children until the person asks for the rest.
export const TRACE_DIALOG_CHILD_LIMIT = 10

export type TraceDialogRow = { kind: 'span'; node: SpanNode } | { kind: 'more'; parent: SpanNode; hiddenCount: number }

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
 * The rows the span list shows, depth first in start order. A collapsed span hides its subtree, and a
 * span with more than TRACE_DIALOG_CHILD_LIMIT children shows the first ones and a "more" row, unless
 * its children are shown in full. The pinned span stays visible past the limit, so the span a log came
 * from is on screen when the dialog opens.
 */
export function buildTraceDialogRows(
    roots: SpanNode[],
    collapsedSpanIds: Set<string>,
    fullChildListSpanIds: Set<string>,
    pinned: SpanNode | null
): TraceDialogRow[] {
    const pinnedPath = new Set<SpanNode>()
    for (let node = pinned; node; node = node.parent) {
        pinnedPath.add(node)
    }

    const rows: TraceDialogRow[] = []
    const stack: TraceDialogRow[] = byStart(roots)
        .reverse()
        .map((node) => ({ kind: 'span', node }))
    while (stack.length > 0) {
        const row = stack.pop()!
        rows.push(row)
        if (row.kind !== 'span') {
            continue
        }
        const { node } = row
        const spanId = node.span.span_id
        if (node.children.length === 0 || collapsedSpanIds.has(spanId)) {
            continue
        }
        let shown = byStart(node.children)
        if (shown.length > TRACE_DIALOG_CHILD_LIMIT && !fullChildListSpanIds.has(spanId)) {
            shown = shown.filter((child, i) => i < TRACE_DIALOG_CHILD_LIMIT || pinnedPath.has(child))
        }
        const next: TraceDialogRow[] = shown.map((child) => ({ kind: 'span', node: child }))
        const hiddenCount = node.children.length - shown.length
        if (hiddenCount > 0) {
            next.push({ kind: 'more', parent: node, hiddenCount })
        }
        for (let i = next.length - 1; i >= 0; i--) {
            stack.push(next[i])
        }
    }
    return rows
}
