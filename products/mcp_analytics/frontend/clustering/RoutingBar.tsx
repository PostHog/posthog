import { Tooltip } from '@posthog/lemon-ui'

import type { MCPIntentClusterApi } from '../generated/api.schemas'
import { routingSegments } from './mcpClusteringLogic'

// The top tool is solid and each subsequent one steps down, so the shape of a cluster's
// routing is readable at a glance without a legend. The bar encodes the split only —
// error rates are on the row and in the detail table.
const SEGMENT_OPACITIES = [1, 0.6, 0.4]

/**
 * A cluster's tool routing as one dense stacked bar. Replaces the cluster × tool heatmap:
 * it answers the same "does this goal go to one tool or many" question in a width that
 * fits a list row beside a detail pane.
 *
 * Takes `color` rather than reading the chart theme itself: `useChartTheme` installs a
 * MutationObserver per call, and this renders once per cluster in the list.
 */
export function RoutingBar({ cluster, color }: { cluster: MCPIntentClusterApi; color: string }): JSX.Element | null {
    const segments = routingSegments(cluster)
    if (segments.length === 0) {
        return null
    }

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-0.5">
                    {segments.map((segment, i) => (
                        <span key={i}>
                            <span className="font-mono">
                                {segment.tool ?? `${segment.toolCount} more tool${segment.toolCount === 1 ? '' : 's'}`}
                            </span>{' '}
                            {segment.pct.toFixed(1)}%
                            {segment.errorRatePct > 0 ? (
                                <span className="text-danger"> · {segment.errorRatePct.toFixed(1)}% errors</span>
                            ) : null}
                        </span>
                    ))}
                </div>
            }
        >
            <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-sm bg-surface-secondary">
                {segments.map((segment, i) => (
                    <div
                        key={i}
                        // Width and colour are both data, so neither comes from a utility class.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: `${segment.pct}%`,
                            backgroundColor: segment.tool === null ? 'var(--border-bold)' : color,
                            opacity: segment.tool === null ? 1 : (SEGMENT_OPACITIES[i] ?? 0.4),
                        }}
                    />
                ))}
            </div>
        </Tooltip>
    )
}
