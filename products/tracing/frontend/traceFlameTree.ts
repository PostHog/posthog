import type { FlameNode } from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SpanTreeNode } from '~/queries/schema/schema-general'

import { compareRowKey } from './compareUtils'
import type { FlameTreeNode } from './flameTree'

export type TraceFlameSizeBy = 'p50' | 'total'

/** What each flame node carries into the tooltip: both windows' merged rows. */
export interface TraceFlameMeta {
    serviceName: string
    current: SpanTreeNode | null
    previous: SpanTreeNode | null
}

const ROOT_KEY = '\u0000<ROOT>'

// The same key as the operation rows of the tables, so that a caller can name a node by an operation's key.
export function nodeKey(node: { serviceName: string; name: string }): string {
    return compareRowKey({ service_name: node.serviceName, name: node.name })
}

// A weighted average would let one rare, slow call site pull the whole node up.
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

// The tree query returns one row per parent edge, so a span with several parents has several rows.
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

export function buildTree(current: SpanTreeNode[], previous: SpanTreeNode[] | null): FlameTreeNode {
    const allNodes = new Map<string, { currentRows: SpanTreeNode[]; previousRows: SpanTreeNode[] }>()
    const childrenByParent = new Map<string, Set<string>>()

    function record(row: SpanTreeNode, isCurrent: boolean): void {
        const key = compareRowKey(row)
        if (!allNodes.has(key)) {
            allNodes.set(key, { currentRows: [], previousRows: [] })
        }
        const entry = allNodes.get(key)!
        if (isCurrent) {
            entry.currentRows.push(row)
        } else {
            entry.previousRows.push(row)
        }

        const parentKey =
            row.parent_name === '<ROOT>'
                ? ROOT_KEY
                : compareRowKey({ service_name: row.parent_service, name: row.parent_name })
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

    // Edges grouped by name can form a cycle, so skip children already on the path.
    function build(key: string, serviceName: string, name: string, ancestors: Set<string>): FlameTreeNode {
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

export interface TraceFlameOptions {
    sizeBy: TraceFlameSizeBy
    /** False for a single trace, which has no previous window to compare against. */
    hasBaseline: boolean
    errorColor?: string
}

export function toFlameNodes(
    root: FlameTreeNode,
    { sizeBy, hasBaseline, errorColor }: TraceFlameOptions
): FlameNode<TraceFlameMeta>[] {
    const field = sizeBy === 'total' ? 'total_duration_nano' : 'p50_duration_nano'
    // The chart reads a value of 0 as a missing span, so a zero-duration span that exists gets 1 ns.
    const size = (node: SpanTreeNode | null): number => (node ? Math.max(node[field], 1) : 0)
    // A zero baseline has no ratio, so like the compare table it reads as unchanged rather than infinitely slower.
    const baselineSize = (node: FlameTreeNode): number =>
        node.node && node.previousNode?.[field] === 0 ? size(node.node) : size(node.previousNode)
    const roots: FlameNode<TraceFlameMeta>[] = []
    // A single trace can nest thousands of spans deep, which would overflow the stack if this recursed.
    const stack: { node: FlameTreeNode; parentId: string; siblings: FlameNode<TraceFlameMeta>[] }[] = root.children
        .map((node) => ({ node, parentId: '', siblings: roots }))
        .reverse()
    while (stack.length > 0) {
        const { node, parentId, siblings } = stack.pop()!
        const id = flameId(parentId, node)
        const current = node.node
        const children: FlameNode<TraceFlameMeta>[] = []
        siblings.push({
            id,
            name:
                !hasBaseline && current && current.count > 1
                    ? `${node.name} ×${humanFriendlyNumber(current.count)}`
                    : node.name,
            group: node.serviceName,
            value: size(current),
            baselineValue: hasBaseline ? baselineSize(node) : undefined,
            count: current?.count,
            baselineCount: hasBaseline ? (node.previousNode?.count ?? 0) : undefined,
            color: !hasBaseline && (current?.error_count ?? 0) > 0 ? errorColor : undefined,
            meta: { serviceName: node.serviceName, current, previous: node.previousNode },
            children,
        })
        for (let i = node.children.length - 1; i >= 0; i--) {
            stack.push({ node: node.children[i], parentId: id, siblings: children })
        }
    }
    return roots
}

function flameId(parentId: string, node: FlameTreeNode): string {
    return `${parentId}/${nodeKey(node)}`
}

export function flameIdOf(path: FlameTreeNode[]): string {
    return path.reduce(flameId, '')
}
