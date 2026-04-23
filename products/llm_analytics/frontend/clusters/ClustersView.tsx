import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconGear, IconInfo, IconQuestion, IconStack } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ClusterCard } from './ClusterCard'
import { ClusterDistributionBar } from './ClusterDistributionBar'
import { ClusteringAdminModal } from './ClusteringAdminModal'
import { clusteringJobsLogic } from './clusteringJobsLogic'
import { ClusteringJobsPanel } from './ClusteringJobsPanel'
import { clustersAdminLogic } from './clustersAdminLogic'
import { ClusterScatterPlot } from './ClusterScatterPlot'
import { clustersLogic } from './clustersLogic'
import { NOISE_CLUSTER_ID } from './constants'
import { EvaluationFilterBar } from './EvaluationFilterBar'
import { Cluster, ClusteringLevel, getJobIdFromRunId } from './types'

export function ClustersView(): JSX.Element {
    const {
        clusteringLevel,
        clusteringRuns,
        clusteringRunsLoading,
        currentRun,
        currentRunLoading,
        sortedClusters,
        filteredSortedClusters,
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
    const { jobs } = useValues(clusteringJobsLogic)
    const { openJobsPanel } = useActions(clusteringJobsLogic)

    const showAdminPanel = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERING_ADMIN]
    const evaluationsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_CLUSTERING]
    const levelOptions: { value: ClusteringLevel; label: string }[] = [
        { value: 'trace', label: 'Traces' },
        { value: 'generation', label: 'Generations' },
        ...(evaluationsEnabled ? [{ value: 'evaluation' as const, label: 'Evaluations' }] : []),
    ]
    const levelTooltip = evaluationsEnabled
        ? 'Traces cluster entire conversations, generations cluster individual LLM calls, and evaluations cluster $ai_evaluation events by evaluator name, verdict, and reasoning'
        : 'Traces cluster entire conversations, while generations cluster individual LLM calls'

    // Build a map from job_id to job name for run labels
    const jobNameById: Record<string, string> = {}
    for (const job of jobs) {
        jobNameById[String(job.id)] = job.name
    }

    if (clusteringRunsLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner className="text-2xl" captureTime />
            </div>
        )
    }

    // Show empty state only after checking both trace and generation levels
    // Always show the level toggle so users can switch between levels
    const showEmptyState = clusteringRuns.length === 0

    if (showEmptyState) {
        return (
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    {/* Level toggle is always visible so users can switch */}
                    <div className="flex items-center gap-3">
                        <Tooltip title={levelTooltip} placement="bottom">
                            <span>
                                <LemonSegmentedButton
                                    value={clusteringLevel}
                                    onChange={(value) => setClusteringLevel(value as ClusteringLevel)}
                                    options={levelOptions}
                                    size="small"
                                    data-attr="clusters-level-toggle"
                                />
                            </span>
                        </Tooltip>
                    </div>

                    <div className="flex items-center gap-4">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconStack />}
                            onClick={openJobsPanel}
                            tooltip="Manage clustering jobs"
                            data-attr="clusters-jobs-button"
                            status="default"
                        >
                            {jobs.length > 0 ? `Jobs (${jobs.length})` : 'Jobs'}
                        </LemonButton>

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

                <div className="flex flex-col items-center justify-center p-8 text-center">
                    <h3 className="text-lg font-semibold mb-2">
                        No{' '}
                        {clusteringLevel === 'generation'
                            ? 'generation'
                            : clusteringLevel === 'evaluation'
                              ? 'evaluation'
                              : 'trace'}{' '}
                        clustering runs found
                    </h3>
                    <p className="text-muted max-w-md">
                        {clusteringLevel === 'trace'
                            ? 'Try switching to "Generations" or "Evaluations" to see other clusters, or check back later once more data has been collected.'
                            : clusteringLevel === 'generation'
                              ? 'Try switching to "Traces" or "Evaluations" to see other clusters, or check back later once more data has been collected.'
                              : 'Try switching to "Traces" or "Generations" to see other clusters, or check back later once more data has been collected.'}
                    </p>
                </div>

                <ClusteringJobsPanel />

                {showAdminPanel && <ClusteringAdminModal />}
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {/* Run Selector Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Tooltip title={levelTooltip} placement="bottom">
                        <span>
                            <LemonSegmentedButton
                                value={clusteringLevel}
                                onChange={(value) => setClusteringLevel(value as ClusteringLevel)}
                                options={levelOptions}
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
                                options={clusteringRuns.map((run: { runId: string; label: string }) => {
                                    const jobId = getJobIdFromRunId(run.runId)
                                    const jobName = jobId ? jobNameById[jobId] : null
                                    return {
                                        value: run.runId,
                                        label: jobName ? `${run.label} (${jobName})` : run.label,
                                    }
                                })}
                                placeholder="Select a run"
                                data-attr="clusters-run-select"
                            />
                        </span>
                    </Tooltip>
                </div>

                <div className="flex items-center gap-4">
                    {currentRun &&
                        (() => {
                            const outlierCluster = sortedClusters.find(
                                (c: Cluster) => c.cluster_id === NOISE_CLUSTER_ID
                            )
                            const regularClusterCount = sortedClusters.filter(
                                (c: Cluster) => c.cluster_id !== NOISE_CLUSTER_ID
                            ).length
                            const outlierCount = outlierCluster?.size || 0
                            const itemNoun =
                                clusteringLevel === 'generation'
                                    ? 'generations'
                                    : clusteringLevel === 'evaluation'
                                      ? 'evaluations'
                                      : 'traces'
                            const clustersLabel =
                                outlierCount > 0
                                    ? `${regularClusterCount} clusters, ${outlierCount} outliers`
                                    : `${regularClusterCount} clusters`
                            const windowLabel = `${dayjs(currentRun.windowStart).format('MMM D')} - ${dayjs(
                                currentRun.windowEnd
                            ).format('MMM D, YYYY')}`
                            return (
                                <Tooltip
                                    title={
                                        <div className="flex flex-col gap-1">
                                            <span>
                                                {currentRun.totalItemsAnalyzed} {itemNoun} analyzed
                                            </span>
                                            <span>{clustersLabel}</span>
                                            <span>{windowLabel}</span>
                                        </div>
                                    }
                                >
                                    <IconInfo className="text-muted text-base shrink-0" />
                                </Tooltip>
                            )
                        })()}

                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconStack />}
                        onClick={openJobsPanel}
                        tooltip="Manage clustering jobs"
                        data-attr="clusters-jobs-button"
                        status="default"
                    >
                        {jobs.length > 0 ? `Jobs (${jobs.length})` : 'Jobs'}
                    </LemonButton>

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
                    <Spinner className="text-2xl" captureTime />
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
                            <ClusterDistributionBar clusters={filteredSortedClusters} runId={effectiveRunId || ''} />
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
                            <div className="flex items-center justify-between mt-2">
                                <span className="text-xs text-muted">Drag to zoom &middot; Double-click to reset</span>
                                <Tooltip
                                    title={
                                        <div className="space-y-1.5">
                                            <p className="font-semibold mb-0">WTH (What The Hog) is this?</p>
                                            <p className="mb-0">
                                                Each dot is a{' '}
                                                {clusteringLevel === 'generation' ? 'generation' : 'trace'}. We crunched
                                                them through embeddings and squished them into 2D so similar ones land
                                                near each other.
                                            </p>
                                            <p className="mb-0">
                                                Clusters of dots = groups of{' '}
                                                {clusteringLevel === 'generation' ? 'generations' : 'traces'} that your
                                                LLM handled in a similar way. Outliers are the loners that didn't fit
                                                any group.
                                            </p>
                                            <p className="mb-0">
                                                Click any dot to drill into that specific{' '}
                                                {clusteringLevel === 'generation' ? 'generation' : 'trace'}.
                                            </p>
                                        </div>
                                    }
                                    placement="left"
                                    docLink="https://posthog.com/docs/llm-analytics/clusters"
                                >
                                    <span
                                        className="inline-flex items-center gap-1 text-xs text-muted hover:text-default cursor-pointer transition-colors"
                                        data-attr="clusters-scatter-plot-wth"
                                    >
                                        <IconQuestion className="text-sm" />
                                        WTH is this?
                                    </span>
                                </Tooltip>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Eval-only post-hoc filter (renders below the scatter, above the cards) */}
            {!currentRunLoading && sortedClusters.length > 0 && <EvaluationFilterBar />}

            {/* Empty result after filtering */}
            {!currentRunLoading && sortedClusters.length > 0 && filteredSortedClusters.length === 0 && (
                <div className="border rounded-lg p-6 text-center text-muted">
                    No clusters match the current evaluation filters.
                </div>
            )}

            {/* Cluster Cards */}
            {!currentRunLoading && filteredSortedClusters.length > 0 && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {filteredSortedClusters.map((cluster: Cluster) => (
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

            {/* Jobs Panel */}
            <ClusteringJobsPanel />

            {/* Admin Modal */}
            {showAdminPanel && <ClusteringAdminModal />}
        </div>
    )
}
