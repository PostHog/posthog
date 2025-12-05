import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconGear, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ClusterCard } from './ClusterCard'
import { ClusterScatterPlot } from './ClusterScatterPlot'
import { ClusteringAdminModal } from './ClusteringAdminModal'
import { clustersAdminLogic } from './clustersAdminLogic'
import { clustersLogic } from './clustersLogic'
import { Cluster, NOISE_CLUSTER_ID } from './types'

export function ClustersView(): JSX.Element {
    const {
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
    } = useValues(clustersLogic)
    const { setSelectedRunId, toggleClusterExpanded, toggleScatterPlotExpanded, loadClusteringRuns } =
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

    if (clusteringRuns.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-8 text-center">
                <h3 className="text-lg font-semibold mb-2">No clustering runs found</h3>
                <p className="text-muted max-w-md">
                    Clustering runs are generated automatically when you have enough traced LLM interactions. Check back
                    later once more data has been collected.
                </p>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {/* Run Selector Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <label className="font-medium">Clustering run:</label>
                    <LemonSelect
                        value={effectiveRunId || undefined}
                        onChange={(value) => setSelectedRunId(value || null)}
                        options={clusteringRuns.map((run: { runId: string; label: string }) => ({
                            value: run.runId,
                            label: run.label,
                        }))}
                        placeholder="Select a run"
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={loadClusteringRuns}
                        tooltip="Refresh clustering runs"
                    />
                </div>

                <div className="flex items-center gap-4">
                    {currentRun && (
                        <div className="flex items-center gap-2 text-muted text-sm">
                            <span>{currentRun.totalTracesAnalyzed} traces analyzed</span>
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
                        </div>
                    )}

                    {showAdminPanel && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconGear />}
                            onClick={openModal}
                            tooltip="Run clustering with custom parameters"
                        >
                            Run clustering
                        </LemonButton>
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
                    >
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-base">Cluster visualization</h3>
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
                <div className="flex flex-col gap-4">
                    {sortedClusters.map((cluster: Cluster) => (
                        <ClusterCard
                            key={cluster.cluster_id}
                            cluster={cluster}
                            totalTraces={currentRun?.totalTracesAnalyzed || 0}
                            isExpanded={expandedClusterIds.has(cluster.cluster_id)}
                            onToggleExpand={() => toggleClusterExpanded(cluster.cluster_id)}
                            traceSummaries={traceSummaries}
                            loadingTraces={traceSummariesLoading}
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
