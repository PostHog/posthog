import { useMemo, useState } from 'react'

import { LemonDropdown, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { SpanTreeNode } from '~/queries/schema/schema-general'

import { formatDuration } from './TraceFlameChart'

interface TreeNode {
    serviceName: string
    name: string
    node: SpanTreeNode | null
    previousNode: SpanTreeNode | null
    children: TreeNode[]
}

const ROW_HEIGHT_PX = 28
const ROOT_KEY = '\u0000<ROOT>'
/** Children whose normalized share is below this fraction get bundled into a "+N more" group. */
const MIN_VISIBLE_FRACTION = 0.01
/** Need at least this many tiny children to bother bundling — a single 0.5% bar isn't worth a popover. */
const MIN_GROUPED_COUNT = 2

function nodeKey(serviceName: string, name: string): string {
    return `${serviceName}\u0000${name}`
}

function nodeSize(n: SpanTreeNode | null): number {
    // Layout metric: p50 latency. A node's typical own-time, not total wall time.
    return n?.p50_duration_nano ?? 0
}

/**
 * Build a tree from the flat (parent_service, parent_name) → (service_name, name) edges.
 * Both windows contribute nodes; previous-only nodes still appear so vanished call sites
 * are visible in the diff.
 */
function buildTree(current: SpanTreeNode[], previous: SpanTreeNode[] | null): TreeNode {
    const allNodes = new Map<string, { current: SpanTreeNode | null; previous: SpanTreeNode | null }>()
    const childrenByParent = new Map<string, Set<string>>()

    function record(row: SpanTreeNode, isCurrent: boolean): void {
        const key = nodeKey(row.service_name, row.name)
        if (!allNodes.has(key)) {
            allNodes.set(key, { current: null, previous: null })
        }
        const entry = allNodes.get(key)!
        if (isCurrent) {
            entry.current = row
        } else {
            entry.previous = row
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

    function build(key: string, serviceName: string, name: string): TreeNode {
        const entry = allNodes.get(key) ?? { current: null, previous: null }
        const childKeys = Array.from(childrenByParent.get(key) ?? [])
        const children = childKeys
            .map((childKey) => {
                const childEntry = allNodes.get(childKey)!
                const ref = childEntry.current ?? childEntry.previous!
                return build(childKey, ref.service_name, ref.name)
            })
            // Order children by typical start offset (left = earlier).
            .sort((a, b) => (a.node?.avg_start_offset_nano ?? 0) - (b.node?.avg_start_offset_nano ?? 0))
        return {
            serviceName,
            name,
            node: entry.current,
            previousNode: entry.previous,
            children,
        }
    }

    return build(ROOT_KEY, '', '<ROOT>')
}

function deltaColor(current: SpanTreeNode | null, previous: SpanTreeNode | null): string {
    if (!current || !previous) {
        // New or vanished — neutral neon.
        return 'rgba(168, 168, 168, 0.6)'
    }
    if (previous.p50_duration_nano === 0) {
        return 'rgba(168, 168, 168, 0.6)'
    }
    const ratio = current.p50_duration_nano / previous.p50_duration_nano
    if (ratio > 1.2) {
        // Worse: red intensity scales with magnitude.
        const intensity = Math.min(0.85, 0.35 + (ratio - 1.2) * 0.5)
        return `rgba(220, 80, 80, ${intensity})`
    }
    if (ratio < 0.8) {
        const intensity = Math.min(0.85, 0.35 + (0.8 - ratio) * 0.5)
        return `rgba(80, 180, 100, ${intensity})`
    }
    return 'rgba(120, 150, 200, 0.45)'
}

interface FlameRowProps {
    node: TreeNode
    depth: number
    /** This node's width as a fraction (0..1) of the row it lives in. */
    fraction: number
}

function FlameRow({ node, fraction }: FlameRowProps): JSX.Element {
    const widthPct = Math.max(0, Math.min(100, fraction * 100))
    const own = nodeSize(node.node)
    const color = deltaColor(node.node, node.previousNode)

    const current = node.node
    const previous = node.previousNode

    const fmtCount = (n: SpanTreeNode | null): string => (n ? humanFriendlyNumber(n.count) : '—')
    const fmtDur = (v: number | undefined): string => (v === undefined ? '—' : formatDuration(v))
    const tooltipContent = (
        <span>
            <strong>{node.name}</strong>
            <br />
            {node.serviceName}
            <br />
            count: {fmtCount(current)}
            {previous ? ` (prev ${fmtCount(previous)})` : ''}
            <br />
            p50: {fmtDur(current?.p50_duration_nano)}
            {previous ? ` (prev ${fmtDur(previous.p50_duration_nano)})` : ''}
            <br />
            p95: {fmtDur(current?.p95_duration_nano)}
            {previous ? ` (prev ${fmtDur(previous.p95_duration_nano)})` : ''}
            {current && current.error_count > 0 ? (
                <>
                    <br />
                    errors: {humanFriendlyNumber(current.error_count)}
                </>
            ) : null}
        </span>
    )

    return (
        <div style={{ width: `${widthPct}%` }} className="flex flex-col min-w-0 shrink-0">
            <Tooltip title={tooltipContent} delayMs={100} placement="top">
                <div
                    className="flex items-center px-2 overflow-hidden min-w-0 text-xs font-mono cursor-pointer border-r border-b border-bg-bg transition-[filter] hover:brightness-125"
                    style={{
                        height: ROW_HEIGHT_PX,
                        backgroundColor: color,
                        // Marker for "new in current window" (no previous data).
                        outline: !previous && current ? '1px dashed rgba(80, 180, 100, 0.85)' : undefined,
                        // Marker for "vanished" (no current data).
                        opacity: !current && previous ? 0.5 : 1,
                    }}
                >
                    <span className="truncate">{node.name}</span>
                </div>
            </Tooltip>
            {node.children.length > 0 && <ChildrenRow parent={node} parentTotal={own} />}
        </div>
    )
}

interface ChildrenRowProps {
    parent: TreeNode
    parentTotal: number
}

/**
 * Lays out one row of children. Their widths are normalized so that visible siblings
 * always sum to 100% — preventing the "spans overlap" effect that happens when
 * aggregate child durations exceed the parent (concurrent execution). Tiny children
 * (< 1% of the visible row) are bundled into a "+N more" cell that opens a popover
 * with that subset rendered at full width.
 */
function ChildrenRow({ parent, parentTotal }: ChildrenRowProps): JSX.Element {
    const childrenWithSize = parent.children.map((child) => ({
        child,
        size: nodeSize(child.node),
    }))
    const totalSize = childrenWithSize.reduce((acc, c) => acc + c.size, 0)
    // Normalization base: use the larger of parent's own total and the summed children
    // total — the latter wins under concurrency so siblings always fit inside 100%.
    const base = Math.max(parentTotal, totalSize, 1)

    const visible: { child: TreeNode; fraction: number }[] = []
    const grouped: { child: TreeNode; fraction: number }[] = []
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
        <div className="flex w-full">
            {visible.map(({ child, fraction }) => (
                <FlameRow key={nodeKey(child.serviceName, child.name)} node={child} depth={0} fraction={fraction} />
            ))}
            {grouped.length > 0 && <GroupedCell items={grouped} fraction={groupedSum + remainder} />}
        </div>
    )
}

interface GroupedCellProps {
    items: { child: TreeNode; fraction: number }[]
    /** Combined width fraction of the bundle inside the row. */
    fraction: number
}

function GroupedCell({ items, fraction }: GroupedCellProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const widthPct = Math.max(0, Math.min(100, fraction * 100))
    // Inside the popover, redistribute the bundle's items to fill the full width.
    const bundleTotal = items.reduce((acc, i) => acc + nodeSize(i.child.node), 0) || 1
    return (
        <LemonDropdown
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="flex flex-col gap-1 max-w-[640px]">
                    <div className="text-xs text-muted px-1">{items.length} small spans</div>
                    <div className="flex w-full" style={{ minWidth: 480 }}>
                        {items
                            .slice()
                            .sort((a, b) => nodeSize(b.child.node) - nodeSize(a.child.node))
                            .map((item) => (
                                <FlameRow
                                    key={nodeKey(item.child.serviceName, item.child.name)}
                                    node={item.child}
                                    depth={0}
                                    fraction={nodeSize(item.child.node) / bundleTotal}
                                />
                            ))}
                    </div>
                </div>
            }
        >
            <div
                style={{ width: `${widthPct}%`, height: ROW_HEIGHT_PX }}
                className="flex items-center justify-center min-w-0 shrink-0 text-xs cursor-pointer border-r border-b border-bg-bg bg-fill-tertiary hover:brightness-110"
                onClick={() => setOpen(!open)}
                role="button"
                tabIndex={0}
            >
                <span className="truncate px-1 text-muted">+ {items.length} more</span>
            </div>
        </LemonDropdown>
    )
}

interface TraceCompareFlameProps {
    current: SpanTreeNode[]
    previous: SpanTreeNode[] | null
    loading: boolean
}

export function TraceCompareFlame({ current, previous, loading }: TraceCompareFlameProps): JSX.Element {
    const tree = useMemo(() => buildTree(current, previous), [current, previous])

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
                            backgroundColor: 'rgba(168, 168, 168, 0.6)',
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
            <div className="overflow-x-auto">
                <ChildrenRow parent={tree} parentTotal={tree.children.reduce((sum, c) => sum + nodeSize(c.node), 0)} />
            </div>
        </div>
    )
}
