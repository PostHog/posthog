import { router } from 'kea-router'

import { Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { urls } from 'scenes/urls'

import { NOISE_CLUSTER_ID, OUTLIER_COLOR } from './constants'
import { Cluster } from './types'

interface ClusterDistributionBarProps {
    clusters: Cluster[]
    runId: string
}

export function ClusterDistributionBar({ clusters, runId }: ClusterDistributionBarProps): JSX.Element | null {
    if (clusters.length === 0) {
        return null
    }

    // Calculate total from actual cluster sizes so the bar fills 100%
    const totalInClusters = clusters.reduce((sum, cluster) => sum + cluster.size, 0)

    if (totalInClusters === 0) {
        return null
    }

    return (
        <div className="flex-1 min-w-0 flex items-center">
            <div className="flex w-full h-2.5 rounded-sm overflow-hidden bg-border-light">
                {clusters.map((cluster) => {
                    const percentage = (cluster.size / totalInClusters) * 100
                    const isOutlier = cluster.cluster_id === NOISE_CLUSTER_ID
                    const color = isOutlier ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)

                    if (percentage < 0.5) {
                        return null
                    }

                    return (
                        <Tooltip
                            key={cluster.cluster_id}
                            title={
                                <div className="text-xs">
                                    <div className="font-semibold">{cluster.title}</div>
                                    <div>
                                        {cluster.size} ({Math.round(percentage)}%)
                                    </div>
                                </div>
                            }
                        >
                            <div
                                className="h-full transition-all hover:opacity-80 cursor-pointer"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    width: `${percentage}%`,
                                    backgroundColor: color,
                                }}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    router.actions.push(urls.llmAnalyticsCluster(runId, cluster.cluster_id))
                                }}
                            />
                        </Tooltip>
                    )
                })}
            </div>
        </div>
    )
}
