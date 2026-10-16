import type { Span } from './types'

/**
 * Parse an ISO 8601 timestamp string to microseconds since epoch.
 * `Date.getTime()` only gives millisecond resolution, losing sub-ms
 * precision from timestamps like "2024-01-15T10:30:00.123456Z".
 */
export function parseTimestampUs(iso: string): number {
    const ms = new Date(iso).getTime()
    // Extract fractional seconds beyond milliseconds
    const dot = iso.indexOf('.')
    if (dot === -1) {
        return ms * 1_000
    }
    // Find the end of fractional digits (before 'Z')
    const fracEnd = iso.search(/[Z+-](\d\d:\d\d)?$/i)
    if (fracEnd === -1) {
        return ms * 1_000
    }
    const fracStr = iso.slice(dot + 1, fracEnd)
    // Pad or truncate to 6 digits (microseconds)
    const padded = fracStr.padEnd(6, '0').slice(0, 6)
    const totalUs = parseInt(padded, 10)
    // ms already includes the first 3 fractional digits, so add the remaining sub-ms part
    const subMsUs = totalUs % 1_000
    return ms * 1_000 + subMsUs
}

export interface SpanNode {
    span: Span
    children: SpanNode[]
    depth: number
    isLastChild: boolean
    parent: SpanNode | null
    /** A placeholder for a parent span that is not in the trace. Its children are the spans that point to it. */
    isMissingParent?: boolean
}

const MISSING_PARENT_LABEL = '<parent span missing>'

function missingParentNode(parentSpanId: string, child: Span): SpanNode {
    return {
        span: {
            uuid: `missing-parent-${parentSpanId}`,
            trace_id: child.trace_id,
            span_id: parentSpanId,
            parent_span_id: '',
            name: MISSING_PARENT_LABEL,
            kind: 0,
            service_name: '',
            status_code: 0,
            timestamp: child.timestamp,
            end_time: child.timestamp,
            duration_nano: 0,
            is_root_span: false,
            matched_filter: true,
            attributes: {},
            resource_attributes: {},
        },
        children: [],
        depth: 0,
        isLastChild: false,
        parent: null,
        isMissingParent: true,
    }
}

// A root span has the all-zero OTel parent id, which the API returns as hex ("0000000000000000"), not "".
function parentSpanIdOf(span: Span): string | null {
    if (span.is_root_span || !span.parent_span_id || /^0+$/.test(span.parent_span_id)) {
        return null
    }
    return span.parent_span_id
}

export function buildSpanTree(spans: Span[]): SpanNode[] {
    const byId = new Map<string, SpanNode>()
    const missingParents = new Map<string, SpanNode>()
    const roots: SpanNode[] = []

    for (const span of spans) {
        byId.set(span.span_id, { span, children: [], depth: 0, isLastChild: false, parent: null })
    }

    for (const node of byId.values()) {
        const parentSpanId = parentSpanIdOf(node.span)
        if (parentSpanId && byId.has(parentSpanId)) {
            const parent = byId.get(parentSpanId)!
            parent.children.push(node)
            node.parent = parent
        } else if (parentSpanId) {
            let placeholder = missingParents.get(parentSpanId)
            if (!placeholder) {
                placeholder = missingParentNode(parentSpanId, node.span)
                missingParents.set(parentSpanId, placeholder)
                roots.push(placeholder)
            }
            placeholder.children.push(node)
            node.parent = placeholder
            // The placeholder sorts with the other roots by its earliest child.
            if (parseTimestampUs(node.span.timestamp) < parseTimestampUs(placeholder.span.timestamp)) {
                placeholder.span.timestamp = node.span.timestamp
                placeholder.span.end_time = node.span.timestamp
            }
        } else {
            roots.push(node)
        }
    }

    // Iterative so a deep parent/child chain cannot overflow the call stack.
    const groups: { nodes: SpanNode[]; depth: number }[] = [{ nodes: roots, depth: 0 }]
    while (groups.length > 0) {
        const { nodes, depth } = groups.pop()!
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i]
            node.depth = depth
            node.isLastChild = i === nodes.length - 1
            if (node.children.length > 0) {
                node.children.sort(
                    (a, b) => new Date(a.span.timestamp).getTime() - new Date(b.span.timestamp).getTime()
                )
                groups.push({ nodes: node.children, depth: depth + 1 })
            }
        }
    }

    return roots
}

/**
 * Whether each ancestor level, root first, continues below this node, so the waterfall can draw its tree
 * lines. Derived on demand for the rows on screen: storing it on every node costs memory quadratic in depth.
 */
export function connectorLinesOf(node: SpanNode): boolean[] {
    const lines: boolean[] = []
    for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
        lines.push(!ancestor.isLastChild)
    }
    return lines.reverse()
}

function sortChildren(nodes: SpanNode[]): SpanNode[] {
    return [...nodes].sort((a, b) => parseTimestampUs(a.span.timestamp) - parseTimestampUs(b.span.timestamp))
}

export function countDescendants(node: SpanNode): number {
    let total = 0
    const stack = [...node.children]
    while (stack.length > 0) {
        const current = stack.pop()!
        total += 1
        for (const child of current.children) {
            stack.push(child)
        }
    }
    return total
}

/** Depth-first flatten for rendering, skipping the subtree of any collapsed span. */
export function flattenTree(nodes: SpanNode[], collapsedSpanIds: Set<string>): SpanNode[] {
    const result: SpanNode[] = []
    // An explicit stack, in reverse so the earliest child pops first, keeps deep traces off the call stack.
    const stack = sortChildren(nodes).reverse()
    while (stack.length > 0) {
        const node = stack.pop()!
        result.push(node)
        if (!collapsedSpanIds.has(node.span.span_id)) {
            const children = sortChildren(node.children)
            for (let i = children.length - 1; i >= 0; i--) {
                stack.push(children[i])
            }
        }
    }
    return result
}

/** span_ids of every node that has children — the set of spans that can be collapsed. */
export function collectCollapsibleSpanIds(nodes: SpanNode[]): Set<string> {
    const ids = new Set<string>()
    const stack = [...nodes]
    while (stack.length > 0) {
        const node = stack.pop()!
        if (node.children.length > 0) {
            ids.add(node.span.span_id)
        }
        for (const child of node.children) {
            stack.push(child)
        }
    }
    return ids
}

/** Generate evenly spaced tick marks for the timeline (in microseconds) */
export function getTimelineTicks(durationUs: number): number[] {
    if (durationUs <= 0) {
        return []
    }
    const targetTickCount = 5
    const rawInterval = durationUs / targetTickCount
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawInterval)))
    const niceIntervals = [1, 2, 5, 10]
    const interval = niceIntervals.find((n) => n * magnitude >= rawInterval)! * magnitude
    const ticks: number[] = []
    for (let t = interval; t < durationUs; t += interval) {
        ticks.push(t)
    }
    return ticks
}
