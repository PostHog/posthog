import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconGear, IconInfo } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ClusterCard } from './ClusterCard'
import { ClusterDistributionBar } from './ClusterDistributionBar'
import { ClusterScatterPlot } from './ClusterScatterPlot'
import { ClusteringAdminModal } from './ClusteringAdminModal'
import { clustersAdminLogic } from './clustersAdminLogic'
import { clustersLogic } from './clustersLogic'
import { NOISE_CLUSTER_ID } from './constants'
import { Cluster, ClusteringLevel, ClusteringParams } from './types'

function ClusteringParamsTooltip({ params }: { params: ClusteringParams }): JSX.Element {
    const formatMethodParams = (methodParams: Record<string, unknown>): string => {
        if (!methodParams || Object.keys(methodParams).length === 0) {
            return 'default'
        }
        return Object.entries(methodParams)
            .map(([key, value]) => `${key}: ${value}`)
            .join(', ')
    }

    return (
        <div className="text-xs space-y-0.5 min-w-64">
            <div className="font-semibold mb-2">Clustering parameters</div>
            <div className="flex justify-between gap-4">
                <span className="opacity-70 shrink-0">Clustering</span>
                <span className="font-medium text-right">{params.clustering_method}</span>
            </div>
            {Object.keys(params.clustering_method_params || {}).length > 0 && (
                <div className="flex justify-between gap-4">
                    <span className="opacity-70 shrink-0">Method params</span>
                    <span className="font-medium text-right">
                        {formatMethodParams(params.clustering_method_params)}
                    </span>
                </div>
            )}
            <div className="flex justify-between gap-4">
                <span className="opacity-70 shrink-0">Dim. reduction</span>
                <span className="font-medium text-right">
                    {params.dimensionality_reduction_method}
                    {params.dimensionality_reduction_method !== 'none' &&
                        ` (${params.dimensionality_reduction_ndims}d)`}
                </span>
            </div>
            <div className="flex justify-between gap-4">
                <span className="opacity-70 shrink-0">Visualization</span>
                <span className="font-medium text-right">{params.visualization_method}</span>
            </div>
            <div className="flex justify-between gap-4">
                <span className="opacity-70 shrink-0">Normalization</span>
                <span className="font-medium text-right">{params.embedding_normalization}</span>
            </div>
            <div className="flex justify-between gap-4">
                <span className="opacity-70 shrink-0">Max samples</span>
                <span className="font-medium text-right">{params.max_samples.toLocaleString()}</span>
            </div>
        </div>
    )
}

export function ClustersView(): JSX.Element {
    const {
        clusteringLevel,
        clusteringRuns,
        clusteringRunsLoading,
        currentRun,
        currentRunLoading,
        sortedClusters,
        effectiveRunId,
        expandedClusterIds,
        traceSummaries,
        traceSummariesLoading,
        isScatterPlotExpanded,
        clusterMetrics,
        clusterMetricsLoading,
    } = useValues(clustersLogic)
    const { setClusteringLevel, setSelectedRunId, toggleClusterExpanded, toggleScatterPlotExpanded } =
        useActions(clustersLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openModal } = useActions(clustersAdminLogic)

    const showAdminPanel = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERING_ADMIN]

    if (clusteringRunsLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    // Show empty state only after checking both trace and generation levels
    // Always show the level toggle so users can switch between levels
    const showEmptyState = clusteringRuns.length === 0

    if (showEmptyState) {
        return (
            <div className="space-y-4">
                {/* Level toggle is always visible so users can switch */}
                <div className="flex items-center gap-3">
                    <Tooltip
                        title="Traces cluster entire conversations, while generations cluster individual LLM calls"
                        placement="bottom"
                    >
                        <span>
                            <LemonSegmentedButton
                                value={clusteringLevel}
                                onChange={(value) => setClusteringLevel(value as ClusteringLevel)}
                                options={[
                                    { value: 'trace', label: 'Traces' },
                                    { value: 'generation', label: 'Generations' },
                                ]}
                                size="small"
                                data-attr="clusters-level-toggle"
                            />
                        </span>
                    </Tooltip>
                </div>

                <div className="flex flex-col items-center justify-center p-8 text-center">
                    <h3 className="text-lg font-semibold mb-2">
                        No {clusteringLevel === 'generation' ? 'generation' : 'trace'} clustering runs found
                    </h3>
                    <p className="text-muted max-w-md">
                        {clusteringLevel === 'trace'
                            ? 'Try switching to "Generations" to see generation-level clusters, or check back later once more data has been collected.'
                            : 'Try switching to "Traces" to see trace-level clusters, or check back later once more data has been collected.'}
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {/* Run Selector Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Tooltip
                        title="Traces cluster entire conversations, while generations cluster individual LLM calls"
                        placement="bottom"
                    >
                        <span>
                            <LemonSegmentedButton
                                value={clusteringLevel}
                                onChange={(value) => setClusteringLevel(value as ClusteringLevel)}
                                options={[
                                    { value: 'trace', label: 'Traces' },
                                    { value: 'generation', label: 'Generations' },
                                ]}
                                size="small"
                                data-attr="clusters-level-toggle"
                            />
                        </span>
                    </Tooltip>
                    <span className="text-muted">|</span>
                    <Tooltip title="Clustering run">
                        <span>
                            <LemonSelect
                                value={effectiveRunId || undefined}
                                onChange={(value) => setSelectedRunId(value || null)}
                                options={clusteringRuns.map((run: { runId: string; label: string }) => ({
                                    value: run.runId,
                                    label: run.label,
                                }))}
                                placeholder="Select a run"
                                data-attr="clusters-run-select"
                            />
                        </span>
                    </Tooltip>
                </div>

                <div className="flex items-center gap-4">
                    {currentRun && (
                        <div className="flex items-center gap-2 text-muted text-sm whitespace-nowrap">
                            <span>
                                {currentRun.totalItemsAnalyzed}{' '}
                                {clusteringLevel === 'generation' ? 'generations' : 'traces'} analyzed
                            </span>
                            <span>|</span>
                            <span>
                                {(() => {
                                    const outlierCluster = sortedClusters.find(
                                        (c: Cluster) => c.cluster_id === NOISE_CLUSTER_ID
                                    )
                                    const regularClusterCount = sortedClusters.filter(
                                        (c: Cluster) => c.cluster_id !== NOISE_CLUSTER_ID
                                    ).length
                                    const outlierCount = outlierCluster?.size || 0

                                    if (outlierCount > 0) {
                                        return `${regularClusterCount} clusters, ${outlierCount} outliers`
                                    }
                                    return `${regularClusterCount} clusters`
                                })()}
                            </span>
                            <span>|</span>
                            <span>
                                {dayjs(currentRun.windowStart).format('MMM D')} -{' '}
                                {dayjs(currentRun.windowEnd).format('MMM D, YYYY')}
                            </span>
                            {currentRun.clusteringParams && (
                                <Tooltip
                                    title={<ClusteringParamsTooltip params={currentRun.clusteringParams} />}
                                    placement="bottom"
                                >
                                    <IconInfo className="text-muted-alt cursor-help" />
                                </Tooltip>
                            )}
                        </div>
                    )}

                    {showAdminPanel && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGear />}
                                onClick={openModal}
                                tooltip="Run clustering with custom parameters"
                                data-attr="clusters-run-clustering-button"
                            >
                                Run clustering
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </div>
            </div>

            {/* Loading State */}
            {currentRunLoading && (
                <div className="flex items-center justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            )}

            {/* Scatter Plot Visualization */}
            {!currentRunLoading && !traceSummariesLoading && sortedClusters.length > 0 && (
                <div className="border rounded-lg bg-surface-primary overflow-hidden transition-all">
                    <div
                        className="p-4 cursor-pointer hover:bg-surface-secondary transition-colors"
                        onClick={toggleScatterPlotExpanded}
                        data-attr="clusters-scatter-plot-toggle"
                    >
                        <div className="flex items-center gap-4">
                            <ClusterDistributionBar clusters={sortedClusters} runId={effectiveRunId || ''} />
                            <LemonButton
                                size="small"
                                noPadding
                                icon={isScatterPlotExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    toggleScatterPlotExpanded()
                                }}
                            />
                        </div>
                    </div>
                    {isScatterPlotExpanded && (
                        <div className="border-t p-4">
                            <ClusterScatterPlot traceSummaries={traceSummaries} />
                        </div>
                    )}
                </div>
            )}

            {/* Cluster Cards */}
            {!currentRunLoading && sortedClusters.length > 0 && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {sortedClusters.map((cluster: Cluster) => (
                        <ClusterCard
                            key={cluster.cluster_id}
                            cluster={cluster}
                            totalTraces={currentRun?.totalItemsAnalyzed || 0}
                            isExpanded={expandedClusterIds.has(cluster.cluster_id)}
                            onToggleExpand={() => toggleClusterExpanded(cluster.cluster_id)}
                            traceSummaries={traceSummaries}
                            loadingTraces={traceSummariesLoading}
                            runId={effectiveRunId || ''}
                            clusteringLevel={clusteringLevel}
                            metrics={clusterMetrics[cluster.cluster_id]}
                            metricsLoading={clusterMetricsLoading}
                        />
                    ))}
                </div>
            )}

            {/* Empty State */}
            {!currentRunLoading && sortedClusters.length === 0 && currentRun && (
                <div className="text-center p-8 text-muted">No clusters found in this run.</div>
            )}

            {/* Admin Modal */}
            {showAdminPanel && <ClusteringAdminModal />}
        </div>
    )
}
