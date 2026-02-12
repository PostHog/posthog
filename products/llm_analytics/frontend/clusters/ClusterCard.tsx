import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { formatErrorRate, formatLLMCost, formatLLMLatency, formatTokens } from '../utils'
import { ClusterDescription } from './ClusterDescriptionComponents'
import { ClusterTraceList } from './ClusterTraceList'
import { NOISE_CLUSTER_ID } from './constants'
import { Cluster, ClusterMetrics, ClusteringLevel, TraceSummary } from './types'

interface ClusterCardProps {
    cluster: Cluster
    totalTraces: number
    isExpanded: boolean
    onToggleExpand: () => void
    traceSummaries: Record<string, TraceSummary>
    loadingTraces: boolean
    runId: string
    clusteringLevel?: ClusteringLevel
    metrics?: ClusterMetrics
    metricsLoading?: boolean
}

export function ClusterCard({
    cluster,
    totalTraces,
    isExpanded,
    onToggleExpand,
    traceSummaries,
    loadingTraces,
    runId,
    clusteringLevel = 'trace',
    metrics,
    metricsLoading,
}: ClusterCardProps): JSX.Element {
    const percentage = totalTraces > 0 ? Math.round((cluster.size / totalTraces) * 100) : 0
    const isOutlierCluster = cluster.cluster_id === NOISE_CLUSTER_ID
    const itemLabel = clusteringLevel === 'generation' ? 'generations' : 'traces'

    // Check if we have any metrics to show
    const hasMetrics =
        metrics &&
        (metrics.avgCost !== null ||
            metrics.avgLatency !== null ||
            metrics.avgTokens !== null ||
            metrics.errorRate !== null)

    return (
        <div
            className={`border rounded-lg overflow-hidden transition-all ${
                isOutlierCluster ? 'bg-surface-primary border-dashed border-warning-dark' : 'bg-surface-primary'
            }`}
        >
            {/* Card Header */}
            <div
                className="p-4 cursor-pointer hover:bg-surface-secondary transition-colors"
                onClick={onToggleExpand}
                data-attr="clusters-card-header"
            >
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2 mb-2">
                            <Link
                                to={urls.llmAnalyticsCluster(runId, cluster.cluster_id)}
                                className="font-semibold text-base truncate hover:underline"
                                onClick={(e) => e.stopPropagation()}
                                data-attr="clusters-card-title-link"
                            >
                                {cluster.title}
                            </Link>
                            <LemonTag type={isOutlierCluster ? 'caution' : 'muted'}>
                                {cluster.size} {itemLabel} ({percentage}%)
                            </LemonTag>
                        </div>
                        <ClusterDescription description={cluster.description} />
                        {/* Cluster Metrics */}
                        {metricsLoading && !hasMetrics && (
                            <div className="flex flex-row flex-wrap items-center gap-2 mt-2">
                                {Array.from({ length: 4 }).map((_, i) => (
                                    <div key={i} className="h-5 w-24 bg-border-light rounded animate-pulse" />
                                ))}
                            </div>
                        )}
                        {hasMetrics && (
                            <div className="flex flex-row flex-wrap items-center gap-2 mt-2">
                                {metrics.avgCost !== null && (
                                    <Tooltip title={`Average cost per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Cost: {formatLLMCost(metrics.avgCost)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.avgLatency !== null && (
                                    <Tooltip title={`Average latency per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Latency: {formatLLMLatency(metrics.avgLatency)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.avgTokens !== null && (
                                    <Tooltip title={`Average tokens (input + output) per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Tokens: {formatTokens(metrics.avgTokens)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.errorRate !== null && (
                                    <Tooltip
                                        title={`Error rate: ${metrics.errorCount} of ${metrics.itemCount} ${itemLabel} had errors`}
                                    >
                                        <LemonTag type={metrics.errorRate > 0 ? 'danger' : 'muted'} size="small">
                                            Errors: {formatErrorRate(metrics.errorRate)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.totalCost !== null && (
                                    <Tooltip title={`Total cost across all ${itemLabel} in this cluster`}>
                                        <LemonTag type="muted" size="small">
                                            Total Cost: {formatLLMCost(metrics.totalCost)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </div>
                        )}
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
                    <ClusterTraceList
                        cluster={cluster}
                        traceSummaries={traceSummaries}
                        loading={loadingTraces}
                        clusteringLevel={clusteringLevel}
                    />
                    <div className="p-3 border-t bg-surface-secondary">
                        <Link
                            to={urls.llmAnalyticsCluster(runId, cluster.cluster_id)}
                            className="text-link hover:underline text-sm font-medium"
                            data-attr="clusters-view-all-link"
                        >
                            View all {Object.keys(cluster.traces).length} {itemLabel} →
                        </Link>
                    </div>
                </div>
            )}
        </div>
    )
}
