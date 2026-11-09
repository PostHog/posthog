import clsx from 'clsx'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonDropdown, Link, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SpanTreeNode } from '~/queries/schema/schema-general'

import { CHANGE_THRESHOLD, compareRowKey, MIN_BASELINE_COUNT } from './compareUtils'
import type { TraceViewSurface } from './components/TraceView/traceViewLogic'
import { countFlameNodes, findFlamePath, type FlameTreeNode } from './flameTree'
import { formatDuration } from './TraceWaterfallView'

/** Where the flame sits. Pinned: sent as the `surface` property of analytics events, so keep the values stable. */
export type TraceFlameSurface = TraceViewSurface | 'compare_modal'

const ROW_HEIGHT_PX = 28
const ROOT_KEY = '\u0000<ROOT>'
/** Children whose normalized share is below this fraction get bundled into a "+N more" group. */
const MIN_VISIBLE_FRACTION = 0.01
/** Need at least this many tiny children to bother bundling — a single 0.5% bar isn't worth a popover. */
const MIN_GROUPED_COUNT = 2
/** Floor for the bundled cell so it's always clickable regardless of how small the bundle is. */
const GROUPED_CELL_MIN_WIDTH_PX = 48
const NEUTRAL_BAR_COLOR = 'rgba(168, 168, 168, 0.6)'

type FlameSizeBy = 'p50' | 'total'

interface FlameDisplay {
    sizeBy: FlameSizeBy
    /** False for a single trace, which has no previous window to compare against. */
    hasBaseline: boolean
    serviceColorMap: Map<string, number> | undefined
}

// The same key as the operation rows of the tables, so that a caller can name a node by an operation's key.
function nodeKey(serviceName: string, name: string): string {
    return compareRowKey({ service_name: serviceName, name })
}

function nodeSize(n: FlameTreeNode, sizeBy: FlameSizeBy): number {
    const field = sizeBy === 'total' ? 'total_duration_nano' : 'p50_duration_nano'
    // Layout metric: max of the current and previous value, so vanished and new nodes both
    // claim non-zero space proportional to whichever window they appeared in.
    return Math.max(n.node?.[field] ?? 0, n.previousNode?.[field] ?? 0)
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
function mergeRows(rows: SpanTreeNode[]): SpanTreeNode {
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
function buildTree(current: SpanTreeNode[], previous: SpanTreeNode[] | null): FlameTreeNode {
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

interface DeltaPctProps {
    current: number | null | undefined
    previous: number | null | undefined
    /** When true, increases are bad (red); decreases good (green). For latency/errors. */
    higherIsWorse?: boolean
}

function DeltaPct({ current, previous, higherIsWorse }: DeltaPctProps): JSX.Element | null {
    if (current === null || current === undefined || previous === null || previous === undefined) {
        return null
    }
    if (previous === 0 && current === 0) {
        return null
    }
    if (previous === 0) {
        // Can't compute a percentage from a zero baseline — surface it qualitatively.
        return <span className="text-success ml-1">(new)</span>
    }
    const diff = current - previous
    if (diff === 0) {
        return null
    }
    const pct = (diff / previous) * 100
    const sign = diff > 0 ? '+' : ''
    const worse = higherIsWorse ? diff > 0 : diff < 0
    const color = higherIsWorse === undefined ? 'text-muted' : worse ? 'text-danger' : 'text-success'
    return (
        <span className={`${color} ml-1`}>
            ({sign}
            {pct.toFixed(1)}%)
        </span>
    )
}

function deltaColor(current: SpanTreeNode | null, previous: SpanTreeNode | null): string {
    if (!current || !previous) {
        // New or vanished — neutral neon.
        return NEUTRAL_BAR_COLOR
    }
    if (previous.p50_duration_nano === 0) {
        return NEUTRAL_BAR_COLOR
    }
    // Same low-sample noise guard as the compare table's classification, so a node the table
    // calls unchanged can't render as a deep-red regression here.
    if (Math.min(current.count, previous.count) < MIN_BASELINE_COUNT) {
        return 'rgba(120, 150, 200, 0.45)'
    }
    const ratio = current.p50_duration_nano / previous.p50_duration_nano
    if (ratio > 1 + CHANGE_THRESHOLD) {
        // Worse: red intensity scales with magnitude.
        const intensity = Math.min(0.85, 0.35 + (ratio - (1 + CHANGE_THRESHOLD)) * 0.5)
        return `rgba(220, 80, 80, ${intensity})`
    }
    if (ratio < 1 - CHANGE_THRESHOLD) {
        const intensity = Math.min(0.85, 0.35 + (1 - CHANGE_THRESHOLD - ratio) * 0.5)
        return `rgba(80, 180, 100, ${intensity})`
    }
    return 'rgba(120, 150, 200, 0.45)'
}

function compareBarStyle(node: FlameTreeNode): React.CSSProperties {
    const current = node.node
    const previous = node.previousNode
    return {
        backgroundColor: deltaColor(current, previous),
        // Marker for "new in current window" (no previous data).
        outline: !previous && current ? '1px dashed rgba(80, 180, 100, 0.85)' : undefined,
        // Marker for "vanished" (no current data).
        opacity: !current && previous ? 0.5 : 1,
    }
}

function singleTraceBarStyle(
    node: FlameTreeNode,
    serviceColorMap: Map<string, number> | undefined
): React.CSSProperties {
    if (!serviceColorMap) {
        return { backgroundColor: NEUTRAL_BAR_COLOR }
    }
    // The waterfall uses the same map and the same error color, so a service keeps its color when the view changes.
    const color =
        (node.node?.error_count ?? 0) > 0 ? 'var(--danger)' : getSeriesColor(serviceColorMap.get(node.serviceName) ?? 0)
    return {
        backgroundColor: `color-mix(in srgb, ${color} 35%, transparent)`,
        borderLeft: `1px solid ${color}`,
    }
}

interface FlameRowProps {
    node: FlameTreeNode
    depth: number
    /** This node's width as a fraction (0..1) of the row it lives in. */
    fraction: number
    /** Focus path from the synthetic root down to (and including) this node. */
    selfPath: string[]
    /** Sets the active focus to a given path. */
    onFocus: (path: string[]) => void
    display: FlameDisplay
}

function FlameRow({ node, fraction, selfPath, onFocus, display }: FlameRowProps): JSX.Element {
    const own = nodeSize(node, display.sizeBy)

    const current = node.node
    const previous = node.previousNode
    // In a single trace a bar stands for the spans of one operation under one path of callers, so the count says
    // how many spans that is.
    const label =
        !display.hasBaseline && current && current.count > 1
            ? `${node.name} ×${humanFriendlyNumber(current.count)}`
            : node.name

    const fmtCount = (n: SpanTreeNode | null): string => (n ? humanFriendlyNumber(n.count) : '—')
    const fmtDur = (v: number | undefined): string => (v === undefined ? '—' : formatDuration(v))
    const tooltipContent = (
        <span>
            <strong>{node.name}</strong>
            <br />
            {node.serviceName}
            <br />
            count: {fmtCount(current)}
            <DeltaPct current={current?.count} previous={previous?.count} />
            {previous ? ` (prev ${fmtCount(previous)})` : ''}
            <br />
            p50: {fmtDur(current?.p50_duration_nano)}
            <DeltaPct current={current?.p50_duration_nano} previous={previous?.p50_duration_nano} higherIsWorse />
            {previous ? ` (prev ${fmtDur(previous.p50_duration_nano)})` : ''}
            <br />
            p95: {fmtDur(current?.p95_duration_nano)}
            <DeltaPct current={current?.p95_duration_nano} previous={previous?.p95_duration_nano} higherIsWorse />
            {previous ? ` (prev ${fmtDur(previous.p95_duration_nano)})` : ''}
            <br />
            p99: {fmtDur(current?.p99_duration_nano)}
            <DeltaPct current={current?.p99_duration_nano} previous={previous?.p99_duration_nano} higherIsWorse />
            {previous ? ` (prev ${fmtDur(previous.p99_duration_nano)})` : ''}
            <br />
            total: {fmtDur(current?.total_duration_nano)}
            <DeltaPct current={current?.total_duration_nano} previous={previous?.total_duration_nano} higherIsWorse />
            {previous ? ` (prev ${fmtDur(previous.total_duration_nano)})` : ''}
            {current && current.error_count > 0 ? (
                <>
                    <br />
                    errors: {humanFriendlyNumber(current.error_count)}
                    <DeltaPct current={current.error_count} previous={previous?.error_count} higherIsWorse />
                </>
            ) : null}
        </span>
    )

    return (
        <div
            // flex-grow proportional to fraction, basis 0 so siblings share container width
            // proportionally with no risk of summed widths exceeding 100% (the cause of the
            // visual overlap when using width: X% across rounded percentages).
            style={{ flex: `${Math.max(fraction, 0)} 1 0`, minWidth: 0 }}
            className="flex flex-col overflow-hidden"
        >
            <Tooltip title={tooltipContent} delayMs={100} placement="top">
                <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onFocus(selfPath)}
                    className="flex items-center px-2 overflow-hidden min-w-0 text-xs font-mono cursor-pointer border-r border-b border-bg-bg transition-[filter] hover:brightness-125"
                    style={{
                        height: ROW_HEIGHT_PX,
                        ...(display.hasBaseline
                            ? compareBarStyle(node)
                            : singleTraceBarStyle(node, display.serviceColorMap)),
                    }}
                >
                    <span className="truncate">{label}</span>
                </div>
            </Tooltip>
            {node.children.length > 0 && (
                <ChildrenRow
                    parent={node}
                    parentTotal={own}
                    ancestorPath={selfPath}
                    onFocus={onFocus}
                    display={display}
                />
            )}
        </div>
    )
}

interface ChildrenRowProps {
    parent: FlameTreeNode
    parentTotal: number
    /** Path from the synthetic root to the parent of these children. */
    ancestorPath: string[]
    onFocus: (path: string[]) => void
    display: FlameDisplay
}

/**
 * Lays out one row of children. Their widths are normalized so that visible siblings
 * always sum to 100% — preventing the "spans overlap" effect that happens when
 * aggregate child durations exceed the parent (concurrent execution). Tiny children
 * (< 1% of the visible row) are bundled into a "+N more" cell that opens a popover
 * with that subset rendered at full width.
 */
function ChildrenRow({ parent, parentTotal, ancestorPath, onFocus, display }: ChildrenRowProps): JSX.Element {
    const childrenWithSize = parent.children.map((child) => ({
        child,
        size: nodeSize(child, display.sizeBy),
    }))
    const totalSize = childrenWithSize.reduce((acc, c) => acc + c.size, 0)
    // Normalization base: use the larger of parent's own total and the summed children
    // total — the latter wins under concurrency so siblings always fit inside 100%.
    const base = Math.max(parentTotal, totalSize, 1)

    const visible: { child: FlameTreeNode; fraction: number }[] = []
    const grouped: { child: FlameTreeNode; fraction: number }[] = []
    for (const { child, size } of childrenWithSize) {
        const fraction = size / base
        if (fraction >= MIN_VISIBLE_FRACTION) {
            visible.push({ child, fraction })
        } else {
            grouped.push({ child, fraction })
        }
    }
    // If only one child is below the threshold, don't bother bundling it — show it inline.
    if (grouped.length > 0 && grouped.length < MIN_GROUPED_COUNT) {
        visible.push(...grouped)
        grouped.length = 0
    }

    const visibleSum = visible.reduce((acc, v) => acc + v.fraction, 0)
    const groupedSum = grouped.reduce((acc, v) => acc + v.fraction, 0)
    const remainder = Math.max(0, 1 - visibleSum - groupedSum)

    return (
        <div className="flex w-full min-w-0 overflow-hidden">
            {visible.map(({ child, fraction }) => (
                <FlameRow
                    key={nodeKey(child.serviceName, child.name)}
                    node={child}
                    depth={0}
                    fraction={fraction}
                    selfPath={[...ancestorPath, nodeKey(child.serviceName, child.name)]}
                    onFocus={onFocus}
                    display={display}
                />
            ))}
            {grouped.length > 0 && (
                <GroupedCell
                    items={grouped}
                    fraction={groupedSum + remainder}
                    ancestorPath={ancestorPath}
                    onFocus={onFocus}
                    display={display}
                />
            )}
        </div>
    )
}

interface GroupedCellProps {
    items: { child: FlameTreeNode; fraction: number }[]
    /** Combined width fraction of the bundle inside the row. */
    fraction: number
    ancestorPath: string[]
    onFocus: (path: string[]) => void
    display: FlameDisplay
}

function GroupedCell({ items, fraction, ancestorPath, onFocus, display }: GroupedCellProps): JSX.Element {
    const [open, setOpen] = useState(false)
    // Count every span in the bundled subtrees, not just the top-level grouped children —
    // a single grouped child can hide a deep subtree of small spans.
    const totalSpanCount = items.reduce((acc, i) => acc + countFlameNodes(i.child), 0)
    // Inside the popover, redistribute the bundle's items to fill the full width.
    const bundleTotal = items.reduce((acc, i) => acc + nodeSize(i.child, display.sizeBy), 0) || 1
    return (
        <LemonDropdown
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="flex flex-col gap-1 max-w-[640px]">
                    <div className="text-xs text-muted px-1">{totalSpanCount} small spans</div>
                    <div className="flex w-full" style={{ minWidth: 480 }}>
                        {items
                            .slice()
                            .sort((a, b) => nodeSize(b.child, display.sizeBy) - nodeSize(a.child, display.sizeBy))
                            .map((item) => (
                                <FlameRow
                                    key={nodeKey(item.child.serviceName, item.child.name)}
                                    node={item.child}
                                    depth={0}
                                    fraction={nodeSize(item.child, display.sizeBy) / bundleTotal}
                                    selfPath={[...ancestorPath, nodeKey(item.child.serviceName, item.child.name)]}
                                    onFocus={(p) => {
                                        setOpen(false)
                                        onFocus(p)
                                    }}
                                    display={display}
                                />
                            ))}
                    </div>
                </div>
            }
        >
            <div
                style={{
                    flex: `${Math.max(fraction, 0)} 1 0`,
                    height: ROW_HEIGHT_PX,
                    minWidth: GROUPED_CELL_MIN_WIDTH_PX,
                }}
                className="flex items-center justify-center text-xs cursor-pointer border-r border-b border-bg-bg bg-fill-tertiary hover:brightness-110"
                onClick={() => setOpen(!open)}
                role="button"
                tabIndex={0}
            >
                <span className="truncate px-1 text-muted">+ {totalSpanCount} more</span>
            </div>
        </LemonDropdown>
    )
}

interface TraceCompareFlameProps {
    /**
     * A tree to draw instead of the one built from `current` and `previous`. A single trace passes the tree of its
     * spans, which keeps an operation's calls apart under each caller. The name-merged rows cannot do that. A given tree
     * draws without the compare legend, colors bars by service and labels a bar with its span count.
     */
    tree?: FlameTreeNode
    current: SpanTreeNode[]
    previous: SpanTreeNode[] | null
    loading: boolean
    /** Span name the modal was opened for — the flame initially focuses on this node. */
    initialSpanName?: string | null
    /**
     * The `compareRowKey` of the operation to focus first. It takes the place of `initialSpanName`, because two services
     * can each run an operation of the same name.
     */
    initialFocusKey?: string | null
    /** Which metric sets each bar's width. 'p50' is the per-call cost (the compare view); 'total' is wall-clock time summed over the calls (a single trace). */
    sizeBy?: FlameSizeBy
    /** Colors a single trace's bars by service. Pass the waterfall's map so both views use the same color for a service. */
    serviceColorMap?: Map<string, number>
    /** Where the flame sits, for analytics. */
    surface: TraceFlameSurface
}

export function TraceCompareFlame({
    tree: givenTree,
    current,
    previous,
    loading,
    initialSpanName,
    initialFocusKey,
    sizeBy = 'p50',
    serviceColorMap,
    surface,
}: TraceCompareFlameProps): JSX.Element {
    const tree = useMemo(() => givenTree ?? buildTree(current, previous), [givenTree, current, previous])
    // A given tree is the call tree of one trace, which has no previous window, so the compare legend and the new and
    // vanished markers would describe a comparison that does not exist. The compare modal always builds its tree from
    // rows and keeps them, also when its `previous` is null: before the first tree fetch ends, or when the response has
    // no comparison rows.
    const hasBaseline = givenTree === undefined
    const display = useMemo(
        (): FlameDisplay => ({ sizeBy, hasBaseline, serviceColorMap }),
        [sizeBy, hasBaseline, serviceColorMap]
    )
    // Focus path: keys of nodes from the synthetic root down to the currently focused span.
    // Each click on a flame bar appends; breadcrumb clicks truncate.
    const [focusPath, setFocusPath] = useState<string[]>([])

    // Whenever the tree (or the initial operation we were opened with) changes, reset focus to
    // that operation. The user may then drill in/out via flame clicks and breadcrumb segments.
    // An initial operation that clears on the same tree keeps the drill-down. The trace view clears its
    // highlight when the person switches to another inspector tab, which is no request to leave the bar.
    const lastResetRef = useRef<FlameTreeNode | null>(null)
    useEffect(() => {
        const sameTree = lastResetRef.current === tree
        lastResetRef.current = tree
        if (sameTree && !initialFocusKey && !initialSpanName) {
            return
        }
        const matches = initialFocusKey
            ? (node: FlameTreeNode): boolean => nodeKey(node.serviceName, node.name) === initialFocusKey
            : initialSpanName
              ? (node: FlameTreeNode): boolean => node.name === initialSpanName
              : null
        const path = matches ? findFlamePath(tree, matches) : null
        setFocusPath(path ? path.map((node) => nodeKey(node.serviceName, node.name)) : [])
    }, [tree, initialSpanName, initialFocusKey])

    // Only bar and breadcrumb clicks come through here, so the event counts the person's own drill and not a focus
    // that the flame sets for itself, such as the initial operation or a reset when the tree changes. A click on the
    // bar that already has the focus changes nothing, so it sends nothing.
    const focusByClick = (path: string[]): void => {
        if (path.length !== focusPath.length) {
            // pinned: analytics event and property names, so renaming them breaks the insights built on them
            posthog.capture('tracing trace call tree focused', {
                direction: path.length > focusPath.length ? 'in' : 'out',
                depth: path.length,
                surface,
            })
        }
        setFocusPath(path)
    }

    // Walk the tree to resolve the focused node + its ancestor chain.
    const breadcrumb: FlameTreeNode[] = []
    let focused: FlameTreeNode = tree
    for (const key of focusPath) {
        const next = focused.children.find((c) => nodeKey(c.serviceName, c.name) === key)
        if (!next) {
            break
        }
        focused = next
        breadcrumb.push(focused)
    }

    if (loading) {
        return (
            <div className="relative min-h-32">
                <SpinnerOverlay />
            </div>
        )
    }

    if (tree.children.length === 0) {
        return <div className="text-muted text-center py-8">No spans found in the call tree for this row.</div>
    }

    return (
        <div className="flex flex-col gap-2">
            <FocusBreadcrumb breadcrumb={breadcrumb} onSelect={(depth) => focusByClick(focusPath.slice(0, depth))} />
            <div className="overflow-x-auto">
                {focusPath.length === 0 ? (
                    // No focus → render top-level children directly (the synthetic root has no real bar).
                    <ChildrenRow
                        parent={focused}
                        parentTotal={focused.children.reduce((sum, c) => sum + nodeSize(c, sizeBy), 0)}
                        ancestorPath={focusPath}
                        onFocus={focusByClick}
                        display={display}
                    />
                ) : (
                    // Focused span sits at the top as a full-width bar; its children stack below.
                    <div className="flex">
                        <FlameRow
                            node={focused}
                            depth={0}
                            fraction={1}
                            selfPath={focusPath}
                            onFocus={focusByClick}
                            display={display}
                        />
                    </div>
                )}
            </div>
            {hasBaseline && (
                <div className="flex gap-3 text-xs text-muted">
                    <span className="flex items-center gap-1">
                        <span
                            className="inline-block w-3 h-3 rounded"
                            style={{ backgroundColor: 'rgba(220, 80, 80, 0.7)' }}
                        />
                        slower
                    </span>
                    <span className="flex items-center gap-1">
                        <span
                            className="inline-block w-3 h-3 rounded"
                            style={{ backgroundColor: 'rgba(80, 180, 100, 0.7)' }}
                        />
                        faster
                    </span>
                    <span className="flex items-center gap-1">
                        <span
                            className="inline-block w-3 h-3 rounded"
                            style={{ backgroundColor: 'rgba(120, 150, 200, 0.45)' }}
                        />
                        similar
                    </span>
                    <span className="flex items-center gap-1">
                        <span
                            className="inline-block w-3 h-3 rounded"
                            style={{
                                backgroundColor: NEUTRAL_BAR_COLOR,
                                outline: '1px dashed rgba(80, 180, 100, 0.85)',
                            }}
                        />
                        new
                    </span>
                    <span className="flex items-center gap-1">
                        <span
                            className="inline-block w-3 h-3 rounded"
                            style={{ backgroundColor: 'rgba(168, 168, 168, 0.3)' }}
                        />
                        vanished
                    </span>
                </div>
            )}
        </div>
    )
}

interface FocusBreadcrumbProps {
    breadcrumb: FlameTreeNode[]
    /** Called with the new desired depth (0 = top). */
    onSelect: (depth: number) => void
}

/** Truncate from the left, keeping the most-specific suffix that usually disambiguates span names. */
function truncateLeft(s: string, maxChars: number): string {
    return s.length > maxChars ? '…' + s.slice(-maxChars) : s
}

function FocusBreadcrumb({ breadcrumb, onSelect }: FocusBreadcrumbProps): JSX.Element {
    const items: {
        fullLabel: string
        displayLabel: string
        isCurrent: boolean
        onClick: () => void
        mono?: boolean
    }[] = [
        {
            fullLabel: 'Root',
            displayLabel: 'Root',
            isCurrent: breadcrumb.length === 0,
            onClick: () => onSelect(0),
        },
        ...breadcrumb.map((node, i) => {
            const isCurrent = i === breadcrumb.length - 1
            return {
                fullLabel: node.name,
                displayLabel: truncateLeft(node.name, isCurrent ? 30 : 15),
                isCurrent,
                onClick: () => onSelect(i + 1),
                mono: true,
            }
        }),
    ]
    return (
        <div className="flex items-center gap-x-2 overflow-x-auto">
            {items.map((item, idx) => {
                const truncated = item.displayLabel !== item.fullLabel
                const labelNode = <span className={clsx(item.mono && 'font-mono')}>{item.displayLabel}</span>
                const content = truncated ? <Tooltip title={item.fullLabel}>{labelNode}</Tooltip> : labelNode
                return (
                    <React.Fragment key={idx}>
                        {item.isCurrent ? (
                            <span className="text-sm font-semibold shrink-0">{content}</span>
                        ) : (
                            <Link className="text-sm text-muted shrink-0 whitespace-nowrap" onClick={item.onClick}>
                                {content}
                            </Link>
                        )}
                        {idx < items.length - 1 && <IconChevronRight className="text-base text-muted shrink-0" />}
                    </React.Fragment>
                )
            })}
        </div>
    )
}
