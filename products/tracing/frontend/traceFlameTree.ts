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

    // Cycle guard: the backend's name-grouped edges can describe a cycle
    // (e.g. <ROOT> → A → B → A when traces are crafted recursively). Without this,
    // `build` would recurse indefinitely and freeze the browser tab. We skip any
    // child key that already appears on the current build path.
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
    const convert = (node: FlameTreeNode, parentId: string): FlameNode<TraceFlameMeta> => {
        const id = flameId(parentId, node)
        const current = node.node
        return {
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
            children: node.children.map((child) => convert(child, id)),
        }
    }
    return root.children.map((child) => convert(child, ''))
}

function flameId(parentId: string, node: FlameTreeNode): string {
    return `${parentId}/${nodeKey(node)}`
}

export function flameIdOf(path: FlameTreeNode[]): string {
    return path.reduce(flameId, '')
}
