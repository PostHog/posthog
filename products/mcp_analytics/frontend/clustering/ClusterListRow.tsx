import { memo, useEffect, useRef } from 'react'

import { Badge } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPIntentClusterApi } from '../generated/api.schemas'
import { clusterLabel, formatErrorRate, topToolNames } from './clusterRanking'
import { RoutingBar } from './RoutingBar'

export const ClusterListRow = memo(function ClusterListRow({
    cluster,
    rank,
    isActive,
    onSelect,
    barColor,
}: {
    cluster: MCPIntentClusterApi
    rank: number
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

    const topTools = topToolNames(cluster)

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
            <span className="flex items-start gap-1.5">
                <span className="shrink-0 tabular-nums text-muted">{rank}.</span>
                {/* Labels run long and some are a sentence; two lines beats truncating to a stub. */}
                <span className="font-medium line-clamp-2">{clusterLabel(cluster)}</span>
            </span>
            <RoutingBar cluster={cluster} color={barColor} />
            <span className="truncate font-mono text-secondary" data-attr="mcp-cluster-row-top-tools">
                {topTools.length > 0 ? topTools.join(' · ') : 'no tools recorded'}
            </span>
            <span className="flex items-center gap-1.5 tabular-nums text-secondary">
                {humanFriendlyNumber(cluster.session_count)} session{cluster.session_count === 1 ? '' : 's'}
                <span aria-hidden>·</span>
                {humanFriendlyNumber(cluster.call_count)} calls
                {/* Pill rather than red text, matching how tool quality shows an error rate. */}
                {cluster.error_count > 0 ? (
                    <Badge variant="destructive">{formatErrorRate(cluster.error_rate_pct)}</Badge>
                ) : (
                    <span className="text-muted">0% errors</span>
                )}
            </span>
        </button>
    )
})
