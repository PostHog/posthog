import { useMemo } from 'react'

import { SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

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

function nodeKey(serviceName: string, name: string): string {
    return `${serviceName}\u0000${name}`
}

function totalDuration(n: SpanTreeNode | null): number {
    return n?.total_duration_nano ?? 0
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

interface FlameRowProps {
    node: TreeNode
    depth: number
    parentDurationNano: number
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

function FlameRow({ node, depth, parentDurationNano }: FlameRowProps): JSX.Element {
    // Width fraction relative to parent: a node occupies a slice proportional to its
    // share of the parent's total duration in the current window.
    const own = totalDuration(node.node)
    const widthPct = parentDurationNano > 0 ? Math.min(100, (own / parentDurationNano) * 100) : 100
    const color = deltaColor(node.node, node.previousNode)

    const current = node.node
    const previous = node.previousNode

    const tooltipContent = (
        <div className="text-xs leading-snug">
            <div className="font-mono font-bold">{node.name}</div>
            <div className="text-muted">{node.serviceName}</div>
            <div className="mt-1">
                <div>count: {current ? humanFriendlyNumber(current.count) : '—'}</div>
                {previous && <div className="text-muted text-2xs">prev: {humanFriendlyNumber(previous.count)}</div>}
            </div>
            <div className="mt-1">
                <div>p50: {current ? formatDuration(current.p50_duration_nano) : '—'}</div>
                {previous && (
                    <div className="text-muted text-2xs">prev: {formatDuration(previous.p50_duration_nano)}</div>
                )}
            </div>
            <div className="mt-1">
                <div>p95: {current ? formatDuration(current.p95_duration_nano) : '—'}</div>
                {previous && (
                    <div className="text-muted text-2xs">prev: {formatDuration(previous.p95_duration_nano)}</div>
                )}
            </div>
            {current && current.error_count > 0 && (
                <div className="mt-1 text-danger">errors: {humanFriendlyNumber(current.error_count)}</div>
            )}
        </div>
    )

    return (
        <div style={{ width: `${widthPct}%` }} className="flex flex-col">
            <Tooltip title={tooltipContent}>
                <div
                    className="flex items-center px-2 overflow-hidden text-xs font-mono cursor-default border-r border-b border-bg-bg"
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
            {node.children.length > 0 && (
                <div className="flex w-full">
                    {node.children.map((child) => (
                        <FlameRow
                            key={nodeKey(child.serviceName, child.name)}
                            node={child}
                            depth={depth + 1}
                            parentDurationNano={own}
                        />
                    ))}
                </div>
            )}
        </div>
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
            <div className="flex w-full overflow-x-auto">
                {tree.children.map((child) => (
                    <FlameRow
                        key={nodeKey(child.serviceName, child.name)}
                        node={child}
                        depth={0}
                        parentDurationNano={tree.children.reduce((sum, c) => sum + totalDuration(c.node), 0)}
                    />
                ))}
            </div>
        </div>
    )
}
