import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ClusterDescription } from './ClusterDescriptionComponents'
import { ClusterTraceList } from './ClusterTraceList'
import { NOISE_CLUSTER_ID } from './constants'
import { Cluster, ClusterMetrics, ClusteringLevel, TraceSummary } from './types'

function formatCost(cost: number | null): string {
    if (cost === null) {
        return '-'
    }
    if (cost < 0.0001) {
        return '<$0.0001'
    }
    if (cost < 0.01) {
        return `$${cost.toFixed(4)}`
    }
    return `$${cost.toFixed(2)}`
}

function formatLatency(latency: number | null): string {
    if (latency === null) {
        return '-'
    }
    if (latency < 0.001) {
        return '<1ms'
    }
    if (latency < 1) {
        return `${Math.round(latency * 1000)}ms`
    }
    return `${latency.toFixed(2)}s`
}

function formatTokens(tokens: number | null): string {
    if (tokens === null) {
        return '-'
    }
    if (tokens >= 1000000) {
        return `${(tokens / 1000000).toFixed(1)}M`
    }
    if (tokens >= 1000) {
        return `${(tokens / 1000).toFixed(1)}k`
    }
    return tokens.toFixed(0)
}

function formatErrorRate(errorRate: number | null): string {
    if (errorRate === null) {
        return '-'
    }
    const percentage = errorRate * 100
    if (percentage === 0) {
        return '0%'
    }
    if (percentage < 0.1) {
        return '<0.1%'
    }
    if (percentage < 1) {
        return `${percentage.toFixed(1)}%`
    }
    return `${Math.round(percentage)}%`
}

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
                        {hasMetrics && (
                            <div className="flex items-center gap-4 mt-2 text-xs text-muted">
                                {metrics.avgCost !== null && (
                                    <Tooltip title={`Average cost per ${clusteringLevel}`}>
                                        <span className="flex items-center gap-1">
                                            <span className="font-medium">Avg cost:</span>
                                            <span>{formatCost(metrics.avgCost)}</span>
                                        </span>
                                    </Tooltip>
                                )}
                                {metrics.avgLatency !== null && (
                                    <Tooltip title={`Average latency per ${clusteringLevel}`}>
                                        <span className="flex items-center gap-1">
                                            <span className="font-medium">Avg latency:</span>
                                            <span>{formatLatency(metrics.avgLatency)}</span>
                                        </span>
                                    </Tooltip>
                                )}
                                {metrics.avgTokens !== null && (
                                    <Tooltip title={`Average tokens (input + output) per ${clusteringLevel}`}>
                                        <span className="flex items-center gap-1">
                                            <span className="font-medium">Avg tokens:</span>
                                            <span>{formatTokens(metrics.avgTokens)}</span>
                                        </span>
                                    </Tooltip>
                                )}
                                {metrics.errorRate !== null && (
                                    <Tooltip
                                        title={`Error rate: ${metrics.errorCount} errors out of ${metrics.itemCount} ${itemLabel}`}
                                    >
                                        <span
                                            className={`flex items-center gap-1 ${metrics.errorRate > 0 ? 'text-danger' : ''}`}
                                        >
                                            <span className="font-medium">Errors:</span>
                                            <span>{formatErrorRate(metrics.errorRate)}</span>
                                        </span>
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
