import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { urls } from 'scenes/urls'

import { SentimentBar } from '../components/SentimentTag'
import { formatErrorRate, formatLLMCost, formatLLMLatency, formatTokens } from '../utils'
import { ClusterDescription } from './ClusterDescriptionComponents'
import { ClusterTraceList } from './ClusterTraceList'
import { NOISE_CLUSTER_ID, OUTLIER_COLOR } from './constants'
import { Cluster, ClusteringLevel, TraceSummary } from './types'

interface ClusterCardProps {
    cluster: Cluster
    totalTraces: number
    isExpanded: boolean
    onToggleExpand: () => void
    traceSummaries: Record<string, TraceSummary>
    loadingTraces: boolean
    runId: string
    clusteringLevel?: ClusteringLevel
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
}: ClusterCardProps): JSX.Element {
    const percentage = totalTraces > 0 ? Math.round((cluster.size / totalTraces) * 100) : 0
    const isOutlierCluster = cluster.cluster_id === NOISE_CLUSTER_ID
    const itemLabel = clusteringLevel === 'generation' ? 'generations' : 'traces'

    const clusterColor = isOutlierCluster ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)

    const metrics = cluster.metrics
    const hasMetrics =
        metrics &&
        (metrics.avg_cost !== null ||
            metrics.avg_latency !== null ||
            metrics.avg_tokens !== null ||
            metrics.error_rate !== null ||
            metrics.sentiment !== null)

    return (
        <div
            className={`rounded-lg overflow-hidden transition-all border-y border-r ${
                isOutlierCluster ? 'bg-surface-primary border-dashed' : 'bg-surface-primary'
            }`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: isOutlierCluster ? 'var(--warning-dark)' : 'var(--border)',
                borderLeftWidth: 3,
                borderLeftColor: clusterColor,
                borderLeftStyle: isOutlierCluster ? 'dashed' : 'solid',
            }}
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
                        {/* Cluster Metrics + Sentiment */}
                        {hasMetrics && (
                            <div className="flex flex-row flex-wrap items-center gap-2 mt-2">
                                {metrics.sentiment && (
                                    <Tooltip
                                        title={`Sentiment: ${metrics.sentiment.label} — ${metrics.sentiment.total} ${itemLabel} classified (${metrics.sentiment.counts.positive ?? 0} positive, ${metrics.sentiment.counts.neutral ?? 0} neutral, ${metrics.sentiment.counts.negative ?? 0} negative)`}
                                    >
                                        <span className="flex items-center gap-1.5">
                                            <SentimentBar
                                                label={metrics.sentiment.label}
                                                score={metrics.sentiment.score}
                                            />
                                        </span>
                                    </Tooltip>
                                )}
                                {metrics.avg_cost !== null && (
                                    <Tooltip title={`Average cost per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Cost: {formatLLMCost(metrics.avg_cost)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.avg_latency !== null && (
                                    <Tooltip title={`Average latency per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Latency: {formatLLMLatency(metrics.avg_latency)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.avg_tokens !== null && (
                                    <Tooltip title={`Average tokens (input + output) per ${clusteringLevel}`}>
                                        <LemonTag type="muted" size="small">
                                            Avg Tokens: {formatTokens(metrics.avg_tokens)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.error_rate !== null && (
                                    <Tooltip
                                        title={`Error rate: ${metrics.error_count} of ${metrics.item_count} ${itemLabel} had errors`}
                                    >
                                        <LemonTag type={metrics.error_rate > 0 ? 'danger' : 'muted'} size="small">
                                            Errors: {formatErrorRate(metrics.error_rate)}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {metrics.total_cost !== null && (
                                    <Tooltip title={`Total cost across all ${itemLabel} in this cluster`}>
                                        <LemonTag type="muted" size="small">
                                            Total Cost: {formatLLMCost(metrics.total_cost)}
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
