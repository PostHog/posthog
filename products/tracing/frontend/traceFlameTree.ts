import type { FlameNode } from '@posthog/quill-charts'

import { SpanTreeNode } from '~/queries/schema/schema-general'

export interface TraceTreeNode {
    serviceName: string
    name: string
    node: SpanTreeNode | null
    previousNode: SpanTreeNode | null
    children: TraceTreeNode[]
}

/** What each flame node carries into the tooltip: both windows' merged rows. */
export interface TraceFlameMeta {
    serviceName: string
    current: SpanTreeNode | null
    previous: SpanTreeNode | null
}

const ROOT_KEY = '\u0000<ROOT>'

function nodeKey(serviceName: string, name: string): string {
    return `${serviceName}\u0000${name}`
}

/**
 * Count-weighted median of per-edge percentile values. Each edge contributes its value
 * with its sample count as weight; we walk the sorted values and return the one where
 * cumulative weight crosses half the total. A weighted *average* of medians is dragged
 * far off by a single skewed call site (a rare slow edge pulls the whole node up); the
 * weighted median stays within the range of actually-observed per-edge values.
 */
function weightedMedianByCount(samples: { value: number; count: number }[]): number {
    const sorted = samples.filter((s) => s.count > 0).sort((a, b) => a.value - b.value)
    if (sorted.length === 0) {
        return 0
    }
    const target = sorted.reduce((acc, s) => acc + s.count, 0) / 2
    let cumulative = 0
    for (const s of sorted) {
        cumulative += s.count
        if (cumulative >= target) {
            return s.value
        }
    }
    return sorted[sorted.length - 1].value
}

/**
 * Merge multiple (parent → child) rows that describe the same span into a single node.
 * The backend's tree query emits one row per (parent_service, parent_name, service_name,
 * name) edge, so a span with multiple parents shows up multiple times. Summing across
 * rows is what makes the per-span totals here match the per-span totals in the
 * aggregation list.
 *
 * Percentiles can't be combined exactly without raw samples, so we take the count-weighted
 * median of the per-edge percentiles (see weightedMedianByCount). Means (avg, start offset)
 * combine exactly as a count-weighted average.
 */
export function mergeRows(rows: SpanTreeNode[]): SpanTreeNode {
    let totalCount = 0
    let totalDuration = 0
    let errorCount = 0
    let avgDurationWeighted = 0
    let startOffsetWeighted = 0
    for (const row of rows) {
        totalCount += row.count
        totalDuration += row.total_duration_nano
        errorCount += row.error_count
        avgDurationWeighted += row.avg_duration_nano * row.count
        startOffsetWeighted += row.avg_start_offset_nano * row.count
    }
    const denom = totalCount || 1
    const first = rows[0]
    return {
        ...first,
        count: totalCount,
        total_duration_nano: totalDuration,
        error_count: errorCount,
        p50_duration_nano: weightedMedianByCount(rows.map((r) => ({ value: r.p50_duration_nano, count: r.count }))),
        p95_duration_nano: weightedMedianByCount(rows.map((r) => ({ value: r.p95_duration_nano, count: r.count }))),
        p99_duration_nano: weightedMedianByCount(rows.map((r) => ({ value: r.p99_duration_nano, count: r.count }))),
        p999_duration_nano: weightedMedianByCount(rows.map((r) => ({ value: r.p999_duration_nano, count: r.count }))),
        avg_duration_nano: avgDurationWeighted / denom,
        avg_start_offset_nano: startOffsetWeighted / denom,
    }
}

/**
 * Build a tree from the flat (parent_service, parent_name) → (service_name, name) edges.
 * Both windows contribute nodes; previous-only nodes still appear so vanished call sites
 * are visible in the diff.
 */
export function buildTree(current: SpanTreeNode[], previous: SpanTreeNode[] | null): TraceTreeNode {
    const allNodes = new Map<string, { currentRows: SpanTreeNode[]; previousRows: SpanTreeNode[] }>()
    const childrenByParent = new Map<string, Set<string>>()

    function record(row: SpanTreeNode, isCurrent: boolean): void {
        const key = nodeKey(row.service_name, row.name)
        if (!allNodes.has(key)) {
            allNodes.set(key, { currentRows: [], previousRows: [] })
        }
        const entry = allNodes.get(key)!
        if (isCurrent) {
            entry.currentRows.push(row)
        } else {
            entry.previousRows.push(row)
        }

        const parentKey = row.parent_name === '<ROOT>' ? ROOT_KEY : nodeKey(row.parent_service, row.parent_name)
        if (!childrenByParent.has(parentKey)) {
            childrenByParent.set(parentKey, new Set())
        }
        childrenByParent.get(parentKey)!.add(key)
    }

    for (const row of current) {
        record(row, true)
    }
    for (const row of previous ?? []) {
        record(row, false)
    }

    // Cycle guard: the backend's name-grouped edges can describe a cycle
    // (e.g. <ROOT> → A → B → A when traces are crafted recursively). Without this,
    // `build` would recurse indefinitely and freeze the browser tab. We skip any
    // child key that already appears on the current build path.
    function build(key: string, serviceName: string, name: string, ancestors: Set<string>): TraceTreeNode {
        const entry = allNodes.get(key) ?? { currentRows: [], previousRows: [] }
        const nextAncestors = new Set(ancestors)
        nextAncestors.add(key)
        const childKeys = Array.from(childrenByParent.get(key) ?? []).filter((k) => !ancestors.has(k))
        const children = childKeys
            .map((childKey) => {
                const childEntry = allNodes.get(childKey)!
                const ref = childEntry.currentRows[0] ?? childEntry.previousRows[0]!
                return build(childKey, ref.service_name, ref.name, nextAncestors)
            })
            // Order children by typical start offset (left = earlier).
            .sort((a, b) => (a.node?.avg_start_offset_nano ?? 0) - (b.node?.avg_start_offset_nano ?? 0))
        return {
            serviceName,
            name,
            node: entry.currentRows.length > 0 ? mergeRows(entry.currentRows) : null,
            previousNode: entry.previousRows.length > 0 ? mergeRows(entry.previousRows) : null,
            children,
        }
    }

    return build(ROOT_KEY, '', '<ROOT>', new Set())
}

/**
 * The flame graph's input: one root per top-level span. Width and color follow p50 duration in
 * the current window against the previous one. Without a previous window there is no baseline,
 * so the graph colors by service instead.
 */
export function toFlameNodes(root: TraceTreeNode, hasBaseline: boolean): FlameNode<TraceFlameMeta>[] {
    const convert = (node: TraceTreeNode, parentId: string): FlameNode<TraceFlameMeta> => {
        const id = `${parentId}/${nodeKey(node.serviceName, node.name)}`
        return {
            id,
            name: node.name,
            group: node.serviceName,
            value: node.node?.p50_duration_nano ?? 0,
            baselineValue: hasBaseline ? (node.previousNode?.p50_duration_nano ?? 0) : undefined,
            count: node.node?.count,
            baselineCount: hasBaseline ? (node.previousNode?.count ?? 0) : undefined,
            meta: { serviceName: node.serviceName, current: node.node, previous: node.previousNode },
            children: node.children.map((child) => convert(child, id)),
        }
    }
    return root.children.map((child) => convert(child, ''))
}

/** Flame node id of the first span named `name`, depth first, matching the ids `toFlameNodes` gives. */
export function findFlameIdByName(root: TraceTreeNode, name: string, parentId = ''): string | null {
    for (const child of root.children) {
        const id = `${parentId}/${nodeKey(child.serviceName, child.name)}`
        if (child.name === name) {
            return id
        }
        const nested = findFlameIdByName(child, name, id)
        if (nested) {
            return nested
        }
    }
    return null
}
