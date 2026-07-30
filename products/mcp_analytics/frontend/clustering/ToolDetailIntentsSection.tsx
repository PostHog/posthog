import { useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'

import { urls } from '~/scenes/urls'

import { mcpClusteringLogic } from './mcpClusteringLogic'
import { ToolIntentDetail } from './ToolIntentDetail'

/**
 * The "Intents served" panel on the tool detail page: this tool's slice of the
 * latest intent cluster snapshot. Reads the same snapshot the clustering tab
 * shows, so the numbers always agree between the two surfaces.
 */
export function ToolDetailIntentsSection({ toolName }: { toolName: string }): JSX.Element {
    const { tools, hasSnapshot, snapshotLoading } = useValues(mcpClusteringLogic)
    const tool = tools.find((t) => t.tool === toolName) ?? null

    if (tool) {
        return <ToolIntentDetail tool={tool} showToolLink={false} />
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
