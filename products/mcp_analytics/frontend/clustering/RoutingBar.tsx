import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { MCPIntentClusterApi } from '../generated/api.schemas'
import { routingSegments } from './mcpClusteringLogic'

// The top tool is solid and each subsequent one steps down, so the shape of a
// cluster's routing is readable at a glance without a legend. The bar encodes the
// split only — error rates are on the row and in the detail table, and the danger
// token is too close to the brand one to carry a second meaning here.
const SEGMENT_OPACITIES = ['opacity-100', 'opacity-60', 'opacity-40']

/**
 * A cluster's tool routing as one dense stacked bar. Replaces the cluster × tool
 * heatmap: it answers the same "does this goal go to one tool or many" question in
 * a width that fits a list row beside a detail pane.
 */
export function RoutingBar({ cluster }: { cluster: MCPIntentClusterApi }): JSX.Element | null {
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
                        // brand-red, not accent or primary: those two swap meaning between
                        // the Lemon and quill scopes, so one of them paints nothing here.
                        className={cn(
                            segment.tool === null ? 'bg-border-bold' : 'bg-brand-red',
                            segment.tool === null ? 'opacity-100' : (SEGMENT_OPACITIES[i] ?? 'opacity-40')
                        )}
                        // Width is the datum, so it can't come from the spacing scale.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${segment.pct}%` }}
                    />
                ))}
            </div>
        </Tooltip>
    )
}
