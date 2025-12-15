import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ClusterDescription } from './ClusterDescriptionComponents'
import { ClusterTraceList } from './ClusterTraceList'
import { Cluster, NOISE_CLUSTER_ID, TraceSummary } from './types'

interface ClusterCardProps {
    cluster: Cluster
    totalTraces: number
    isExpanded: boolean
    onToggleExpand: () => void
    traceSummaries: Record<string, TraceSummary>
    loadingTraces: boolean
    runId: string
}

export function ClusterCard({
    cluster,
    totalTraces,
    isExpanded,
    onToggleExpand,
    traceSummaries,
    loadingTraces,
    runId,
}: ClusterCardProps): JSX.Element {
    const percentage = totalTraces > 0 ? Math.round((cluster.size / totalTraces) * 100) : 0
    const isOutlierCluster = cluster.cluster_id === NOISE_CLUSTER_ID

    return (
        <div
            className={`border rounded-lg overflow-hidden transition-all ${
                isOutlierCluster ? 'bg-surface-primary border-dashed border-warning-dark' : 'bg-surface-primary'
            }`}
        >
            {/* Card Header */}
            <div className="p-4 cursor-pointer hover:bg-surface-secondary transition-colors" onClick={onToggleExpand}>
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2 mb-2">
                            <h3 className="font-semibold text-base truncate">{cluster.title}</h3>
                            <LemonTag type={isOutlierCluster ? 'caution' : 'muted'}>
                                {cluster.size} traces ({percentage}%)
                            </LemonTag>
                        </div>
                        <ClusterDescription description={cluster.description} />
                    </div>
                    <LemonButton
                        size="small"
                        noPadding
                        icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onToggleExpand()
                        }}
                    />
                </div>
            </div>

            {/* Expanded Trace List */}
            {isExpanded && (
                <div className="border-t">
                    <ClusterTraceList cluster={cluster} traceSummaries={traceSummaries} loading={loadingTraces} />
                    <div className="p-3 border-t bg-surface-secondary">
                        <Link
                            to={urls.llmAnalyticsCluster(runId, cluster.cluster_id)}
                            className="text-link hover:underline text-sm font-medium"
                        >
                            View all {Object.keys(cluster.traces).length} traces →
                        </Link>
                    </div>
                </div>
            )}
        </div>
    )
}
