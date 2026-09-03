import { memo, useEffect, useRef } from 'react'

import { Badge } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPIntentClusterApi } from '../generated/api.schemas'
import { RoutingBar } from './RoutingBar'

export const ClusterListRow = memo(function ClusterListRow({
    cluster,
    isActive,
    onSelect,
    barColor,
}: {
    cluster: MCPIntentClusterApi
    isActive: boolean
    onSelect: (clusterId: number) => void
    barColor: string
}): JSX.Element {
    const ref = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        // Sorting, filtering, and deep links can all select a row that is scrolled out
        // of view; without this the detail pane changes with nothing visible to explain why.
        if (isActive) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [isActive])

    const topTool = cluster.tool_distribution[0]

    return (
        <button
            ref={ref}
            type="button"
            data-attr="mcp-cluster-row"
            aria-pressed={isActive}
            onClick={() => onSelect(cluster.id)}
            className={cn(
                'w-full text-left cursor-pointer border-l-2 px-2 py-1.5 text-xs flex flex-col gap-1',
                isActive
                    ? 'border-l-accent bg-accent-highlight-secondary'
                    : 'border-l-transparent hover:bg-accent-highlight-secondary'
            )}
        >
            {/* Labels run long and some are a sentence; two lines beats truncating to a stub. */}
            <span className="font-medium line-clamp-2">{cluster.label}</span>
            <RoutingBar cluster={cluster} color={barColor} />
            <div className="flex items-center justify-between gap-2 text-secondary">
                <span className="truncate font-mono">
                    {topTool ? `${topTool.tool} ${topTool.pct.toFixed(0)}%` : 'no tools recorded'}
                </span>
                <span className="flex shrink-0 items-center gap-1.5 tabular-nums">
                    {humanFriendlyNumber(cluster.call_count)} calls
                    {/* Pill rather than red text, matching how tool quality shows an error rate. */}
                    {cluster.error_count > 0 ? (
                        <Badge variant="destructive">{cluster.error_rate_pct.toFixed(1)}%</Badge>
                    ) : null}
                </span>
            </div>
        </button>
    )
})
