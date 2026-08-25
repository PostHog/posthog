import { useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'

import { urls } from '~/scenes/urls'

import { mcpToolIntentsLogic } from './mcpToolIntentsLogic'
import { ToolIntentDetail } from './ToolIntentDetail'

/**
 * The "Intents served" panel on the tool detail page: this tool's slice of the
 * latest intent cluster snapshot. Reads the same snapshot the clustering tab
 * shows — scoped to this tool by the API — so the numbers always agree between
 * the two surfaces without the page downloading every other tool's pivot.
 */
export function ToolDetailIntentsSection({ toolName }: { toolName: string }): JSX.Element {
    const { tool, clusters, hasSnapshot, snapshotLoading, snapshot } = useValues(mcpToolIntentsLogic({ toolName }))

    if (tool) {
        return <ToolIntentDetail tool={tool} clusters={clusters} showToolLink={false} />
    }

    // Mirror the clustering tab's error handling: a failed run must not read as
    // "never computed", or the owner keeps hitting compute with no idea why it fails.
    if (snapshot.status === 'error' && !snapshotLoading) {
        return (
            <div className="bg-surface-primary border rounded p-6 text-center text-muted text-sm">
                The last intent clustering run failed
                {snapshot.error_message ? `: ${snapshot.error_message}` : '.'}{' '}
                <LinkPrimitive to={urls.mcpAnalyticsIntentClustering()} className="text-accent">
                    Retry from the clustering tab
                </LinkPrimitive>
                .
            </div>
        )
    }

    return (
        <div className="bg-surface-primary border rounded p-6 text-center text-muted text-sm">
            {snapshotLoading ? (
                'Loading intent clusters…'
            ) : hasSnapshot ? (
                <>
                    This tool has no intent-attributed calls in the latest cluster snapshot.{' '}
                    <LinkPrimitive to={urls.mcpAnalyticsIntentClustering()} className="text-accent">
                        Recompute clusters
                    </LinkPrimitive>{' '}
                    to include recent traffic.
                </>
            ) : (
                <>
                    Intent clustering shows which goals agents pursue when they call this tool.{' '}
                    <LinkPrimitive to={urls.mcpAnalyticsIntentClustering()} className="text-accent">
                        Compute clusters
                    </LinkPrimitive>{' '}
                    to see them here.
                </>
            )}
        </div>
    )
}
