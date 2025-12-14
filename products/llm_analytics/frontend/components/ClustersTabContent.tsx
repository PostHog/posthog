import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'

interface ClusterInfo {
    runId: string
    runTimestamp: string
    clusterId: number
    clusterTitle: string
    clusterSize: number
    isOutlier: boolean
}

export function ClustersTabContent(): JSX.Element {
    const { traceId } = useValues(llmAnalyticsTraceLogic)
    const [clusters, setClusters] = useState<ClusterInfo[]>([])
    const [loading, setLoading] = useState(true)

    const loadClusters = async (): Promise<void> => {
        setLoading(true)
        try {
            const response = await api.queryHogQL(
                hogql`
                    SELECT
                        JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                        JSONExtractRaw(properties, '$ai_clusters') as clusters_json,
                        timestamp
                    FROM events
                    WHERE event = '$ai_trace_clusters'
                        AND timestamp >= now() - INTERVAL 7 DAY
                    ORDER BY timestamp DESC
                    LIMIT 20
                `,
                { refresh: 'force_blocking' }
            )

            const foundClusters: ClusterInfo[] = []

            for (const row of response.results || []) {
                const [runId, clustersJson, timestamp] = row as [string, string, string]
                try {
                    const clustersData = JSON.parse(clustersJson || '[]')
                    for (const cluster of clustersData) {
                        if (cluster.traces && traceId in cluster.traces) {
                            foundClusters.push({
                                runId,
                                runTimestamp: timestamp,
                                clusterId: cluster.cluster_id,
                                clusterTitle: cluster.title || `Cluster ${cluster.cluster_id}`,
                                clusterSize: cluster.size,
                                isOutlier: cluster.cluster_id === -1,
                            })
                        }
                    }
                } catch {
                    // Skip malformed JSON
                }
            }

            setClusters(foundClusters)
        } catch (error) {
            console.error('Failed to load clusters:', error)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        void loadClusters()
    }, [traceId, loadClusters])

    if (loading) {
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
                    onClick={() => void loadClusters()}
                    loading={loading}
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
