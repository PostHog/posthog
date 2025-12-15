import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { clustersTabContentLogic } from './clustersTabContentLogic'

export function ClustersTabContent(): JSX.Element {
    const { traceId } = useValues(llmAnalyticsTraceLogic)
    const { clusters, clustersLoading } = useValues(clustersTabContentLogic({ traceId }))
    const { loadClusters } = useActions(clustersTabContentLogic({ traceId }))

    if (clustersLoading) {
        return (
            <div className="py-4 space-y-3">
                <LemonSkeleton className="h-8 w-full" />
                <LemonSkeleton className="h-8 w-full" />
                <LemonSkeleton className="h-8 w-full" />
            </div>
        )
    }

    if (clusters.length === 0) {
        return (
            <div className="py-4">
                <div className="text-muted text-center py-8">
                    <p className="mb-2">This trace was not found in any recent clustering runs.</p>
                    <p className="text-sm">
                        Clusters are generated periodically. Run a new clustering workflow to include this trace.
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="py-4">
            <div className="flex justify-between items-center mb-4">
                <h4 className="font-semibold m-0">Clusters containing this trace</h4>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={() => loadClusters()}
                    loading={clustersLoading}
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                dataSource={clusters}
                columns={[
                    {
                        title: 'Cluster',
                        key: 'cluster',
                        render: (_, cluster) => (
                            <div className="flex items-center gap-2">
                                <Link to={urls.llmAnalyticsCluster(cluster.runId, cluster.clusterId)}>
                                    {cluster.clusterTitle}
                                </Link>
                                {cluster.isOutlier && (
                                    <LemonTag type="caution" size="small">
                                        Outlier
                                    </LemonTag>
                                )}
                            </div>
                        ),
                    },
                    {
                        title: 'Size',
                        key: 'size',
                        render: (_, cluster) => <span className="text-muted">{cluster.clusterSize} traces</span>,
                    },
                    {
                        title: 'Run',
                        key: 'run',
                        render: (_, cluster) => (
                            <Link to={urls.llmAnalyticsClusters(cluster.runId)} className="text-muted text-sm">
                                {dayjs(cluster.runTimestamp).format('MMM D, h:mm A')}
                            </Link>
                        ),
                    },
                ]}
                rowKey={(cluster) => `${cluster.runId}-${cluster.clusterId}`}
                emptyState="No clusters found"
            />
        </div>
    )
}
