import { useActions, useValues } from 'kea'

import { LemonSelect, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { ClusterCard } from './ClusterCard'
import { clustersLogic } from './clustersLogic'
import { Cluster } from './types'

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
    } = useValues(clustersLogic)
    const { setSelectedRunId, toggleClusterExpanded } = useActions(clustersLogic)

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
                </div>

                {currentRun && (
                    <div className="flex items-center gap-2 text-muted text-sm">
                        <span>{currentRun.totalTracesAnalyzed} traces analyzed</span>
                        <span>|</span>
                        <span>
                            {dayjs(currentRun.windowStart).format('MMM D')} -{' '}
                            {dayjs(currentRun.windowEnd).format('MMM D, YYYY')}
                        </span>
                    </div>
                )}
            </div>

            {/* Loading State */}
            {currentRunLoading && (
                <div className="flex items-center justify-center p-8">
                    <Spinner className="text-2xl" />
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
        </div>
    )
}
