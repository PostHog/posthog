import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { formatErrorRate, formatLLMCost, formatLLMLatency, formatTokens } from '../utils'
import { BulletList, ClusterDescription, parseBullets } from './ClusterDescriptionComponents'
import { ClusterDetailScatterPlot } from './ClusterDetailScatterPlot'
import { ClusterDetailLogicProps, clusterDetailLogic } from './clusterDetailLogic'
import { TRACES_PER_PAGE } from './constants'
import { ClusterItemInfo, ClusterMetrics, ClusteringLevel, TraceSummary } from './types'

export const scene: SceneExport<ClusterDetailLogicProps> = {
    component: LLMAnalyticsClusterScene,
    logic: clusterDetailLogic,
    productKey: ProductKey.LLM_ANALYTICS,
    paramsToProps: ({ params: { runId, clusterId } }) => ({
        runId: runId ? decodeURIComponent(runId) : '',
        clusterId: clusterId ? parseInt(clusterId, 10) : 0,
    }),
}

export function LLMAnalyticsClusterScene(): JSX.Element {
    const {
        cluster,
        clusterDataLoading,
        clusteringLevel,
        isOutlierCluster,
        totalTraces,
        totalPages,
        currentPage,
        paginatedTracesWithSummaries,
        traceSummariesLoading,
        windowStart,
        windowEnd,
        clusterMetrics,
        clusterMetricsLoading,
    } = useValues(clusterDetailLogic)
    const { setPage } = useActions(clusterDetailLogic)

    if (clusterDataLoading) {
        return (
            <SceneContent>
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-8 w-1/3" />
                    <LemonSkeleton className="h-4 w-2/3" />
                    <div className="flex gap-2">
                        <LemonSkeleton className="h-6 w-24" />
                        <LemonSkeleton className="h-6 w-24" />
                    </div>
                    <div className="space-y-3 mt-4">
                        {[...Array(5)].map((_, i) => (
                            <LemonSkeleton key={i} className="h-20 w-full" />
                        ))}
                    </div>
                </div>
            </SceneContent>
        )
    }

    if (!cluster) {
        return <NotFound object="cluster" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={cluster.title}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <Link to={urls.llmAnalyticsClusters()}>
                        <LemonButton type="secondary" size="small" data-attr="clusters-back-button">
                            Back to clusters
                        </LemonButton>
                    </Link>
                }
            />

            {/* Cluster info header */}
            <div
                className={`border rounded-lg p-4 mb-4 ${
                    isOutlierCluster ? 'bg-surface-primary border-dashed border-warning-dark' : 'bg-surface-primary'
                }`}
            >
                <div className="flex flex-wrap items-center gap-3 mb-2">
                    <LemonTag type={isOutlierCluster ? 'caution' : 'primary'} size="medium">
                        {totalTraces} traces
                    </LemonTag>
                    {windowStart && windowEnd && (
                        <span className="text-muted text-sm">
                            Window: {new Date(windowStart).toLocaleDateString()} -{' '}
                            {new Date(windowEnd).toLocaleDateString()}
                        </span>
                    )}
                </div>
                <ClusterDescription description={cluster.description} />
                <ClusterMetricsChips
                    metrics={clusterMetrics}
                    metricsLoading={clusterMetricsLoading}
                    clusteringLevel={clusteringLevel}
                />
            </div>

            {/* Cluster scatter plot */}
            <div className="border rounded-lg p-4 mb-4 bg-surface-primary">
                <h3 className="font-semibold text-sm mb-2">Cluster visualization</h3>
                <p className="text-muted text-xs mb-3">
                    Each point represents a trace. Click to view details. Drag to zoom, double-click to reset.
                </p>
                <ClusterDetailScatterPlot />
            </div>

            {/* Pagination controls at top */}
            {totalPages > 1 && (
                <div className="flex justify-between items-center mb-4">
                    <span className="text-muted text-sm">
                        Showing {(currentPage - 1) * TRACES_PER_PAGE + 1}-
                        {Math.min(currentPage * TRACES_PER_PAGE, totalTraces)} of {totalTraces} traces
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronLeft />}
                            disabled={currentPage === 1}
                            onClick={() => setPage(currentPage - 1)}
                            data-attr="clusters-detail-prev-page"
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronRight />}
                            disabled={currentPage === totalPages}
                            onClick={() => setPage(currentPage + 1)}
                            data-attr="clusters-detail-next-page"
                        />
                    </div>
                </div>
            )}

            {/* Trace list */}
            <div className="border rounded-lg overflow-hidden divide-y">
                {traceSummariesLoading && paginatedTracesWithSummaries.length === 0 ? (
                    <div className="p-4 flex items-center justify-center">
                        <Spinner className="mr-2" />
                        <span className="text-muted">Loading traces...</span>
                    </div>
                ) : (
                    paginatedTracesWithSummaries.map(
                        (
                            {
                                traceId,
                                traceInfo,
                                summary,
                            }: {
                                traceId: string
                                traceInfo: ClusterItemInfo
                                summary?: TraceSummary
                            },
                            index: number
                        ) => (
                            <TraceListItem
                                key={traceId}
                                traceId={traceId}
                                traceInfo={traceInfo}
                                summary={summary}
                                displayRank={(currentPage - 1) * TRACES_PER_PAGE + index + 1}
                                clusteringLevel={clusteringLevel}
                            />
                        )
                    )
                )}
            </div>

            {/* Pagination controls at bottom */}
            {totalPages > 1 && (
                <div className="flex justify-center mt-4">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronLeft />}
                            disabled={currentPage === 1}
                            onClick={() => setPage(currentPage - 1)}
                            data-attr="clusters-detail-prev-page"
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronRight />}
                            disabled={currentPage === totalPages}
                            onClick={() => setPage(currentPage + 1)}
                            data-attr="clusters-detail-next-page"
                        />
                    </div>
                </div>
            )}
        </SceneContent>
    )
}

function ClusterMetricsChips({
    metrics,
    metricsLoading,
    clusteringLevel,
}: {
    metrics: ClusterMetrics | null
    metricsLoading: boolean
    clusteringLevel: ClusteringLevel
}): JSX.Element | null {
    const hasMetrics =
        metrics &&
        (metrics.avgCost !== null ||
            metrics.avgLatency !== null ||
            metrics.avgTokens !== null ||
            metrics.errorRate !== null)

    if (metricsLoading && !hasMetrics) {
        return (
            <div className="flex flex-row flex-wrap items-center gap-2 mt-2">
                {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-5 w-24 bg-border-light rounded animate-pulse" />
                ))}
            </div>
        )
    }

    if (!hasMetrics) {
        return null
    }

    const itemLabel = clusteringLevel === 'generation' ? 'generations' : 'traces'

    return (
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
                <Tooltip title={`Error rate: ${metrics.errorCount} errors out of ${metrics.itemCount} ${itemLabel}`}>
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
    )
}

function TraceListItem({
    traceId,
    traceInfo,
    summary,
    displayRank,
    clusteringLevel = 'trace',
}: {
    traceId: string
    traceInfo: ClusterItemInfo
    summary?: TraceSummary
    displayRank: number
    clusteringLevel?: ClusteringLevel
}): JSX.Element {
    const [showFlow, setShowFlow] = useState(false)
    const [showBullets, setShowBullets] = useState(false)
    const [showNotes, setShowNotes] = useState(false)

    const bulletItems = summary?.bullets ? parseBullets(summary.bullets) : []
    const noteItems = summary?.interestingNotes ? parseBullets(summary.interestingNotes) : []

    return (
        <div className="p-4 hover:bg-surface-secondary transition-colors">
            {/* Header row with rank, title, and link */}
            <div className="flex items-center gap-2 mb-2">
                <LemonTag type="muted" size="small">
                    #{displayRank}
                </LemonTag>
                <span className="font-medium flex-1 min-w-0 truncate">{summary?.title || 'Loading...'}</span>
                <Link
                    to={urls.llmAnalyticsTrace(clusteringLevel === 'generation' ? traceInfo.trace_id : traceId, {
                        tab: 'summary',
                        // For generation-level, highlight the specific generation
                        ...(clusteringLevel === 'generation' && traceInfo.generation_id
                            ? { event: traceInfo.generation_id }
                            : {}),
                        // timestamp is the trace's first_timestamp for both levels
                        ...(traceInfo.timestamp ? { timestamp: traceInfo.timestamp } : {}),
                    })}
                    className="text-sm text-link hover:underline shrink-0"
                    data-attr="clusters-view-trace-link"
                >
                    {clusteringLevel === 'generation' ? 'View generation →' : 'View trace →'}
                </Link>
            </div>

            {summary ? (
                <div className="space-y-2">
                    {/* Expandable buttons row */}
                    <div className="flex items-center gap-2">
                        {summary.flowDiagram && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showFlow ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowFlow(!showFlow)}
                                data-attr="clusters-trace-flow-toggle"
                            >
                                Flow
                            </LemonButton>
                        )}
                        {bulletItems.length > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showBullets ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowBullets(!showBullets)}
                                data-attr="clusters-trace-summary-toggle"
                            >
                                Summary
                            </LemonButton>
                        )}
                        {noteItems.length > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showNotes ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowNotes(!showNotes)}
                                data-attr="clusters-trace-notes-toggle"
                            >
                                Notes
                            </LemonButton>
                        )}
                    </div>

                    {/* Expanded content */}
                    {showFlow && summary.flowDiagram && (
                        <div className="p-3 bg-surface-tertiary rounded text-sm font-mono whitespace-pre-wrap">
                            {summary.flowDiagram}
                        </div>
                    )}

                    {showBullets && bulletItems.length > 0 && <BulletList items={bulletItems} />}

                    {showNotes && noteItems.length > 0 && <BulletList items={noteItems} />}
                </div>
            ) : (
                <div className="text-muted text-sm">Loading summary...</div>
            )}
        </div>
    )
}
