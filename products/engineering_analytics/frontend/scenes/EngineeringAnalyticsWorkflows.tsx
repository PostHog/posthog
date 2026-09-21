// The full workflow list behind the hub's capped workflows section. Every row opens the workflow page.

import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { RepoEntityHeader } from '../components/EntityHeader'
import { SourceScopeChip, WorkflowScopeControls } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { WorkflowsHealthHeader } from '../components/WorkflowsHealthHeader'
import { WORKFLOW_HEALTH_LIMIT, WorkflowStatusFilter, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

export function EngineeringAnalyticsWorkflows(): JSX.Element {
    const {
        fleetSummary,
        fleetTruncated,
        filteredWorkflowHealth,
        workflowHealth,
        workflowHealthLoading,
        workflowSearch,
        workflowStatusFilter,
        hasActiveWorkflowFilters,
        workflowCostAvailable,
        sourceId,
        activeSource,
        notConnected,
        workflowHealthLoadError,
    } = useValues(engineeringAnalyticsLogic)
    const { setWorkflowSearch, setWorkflowStatusFilter, resetWorkflowFilters, refresh } =
        useActions(engineeringAnalyticsLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (workflowHealthLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    return (
        <div className="flex flex-col gap-4">
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} right={<SourceScopeChip pickerOnly />} />

            {/* Scope + window govern every surface inside the panel, the same scope the overview carries. */}
            <ScopePanel busy={workflowHealthLoading && workflowHealth.length > 0} controls={<WorkflowScopeControls />}>
                <WorkflowsHealthHeader
                    summary={fleetSummary}
                    truncated={fleetTruncated}
                    loading={workflowHealthLoading}
                />

                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search workflows…"
                        value={workflowSearch}
                        onChange={setWorkflowSearch}
                        className="w-64"
                        data-attr="engineering-analytics-workflow-search"
                    />
                    <LemonSegmentedButton
                        size="small"
                        value={workflowStatusFilter}
                        onChange={(value) => setWorkflowStatusFilter(value as WorkflowStatusFilter)}
                        options={[
                            { value: 'all', label: 'All' },
                            {
                                value: 'failing',
                                label: fleetSummary.failingNow > 0 ? `Failing (${fleetSummary.failingNow})` : 'Failing',
                            },
                            { value: 'passing', label: 'Passing' },
                        ]}
                    />
                </div>

                <WorkflowHealthTable
                    rows={filteredWorkflowHealth}
                    loading={workflowHealthLoading}
                    sourceId={sourceId}
                    showCost={workflowCostAvailable}
                    pageSize={25}
                    emptyState={
                        hasActiveWorkflowFilters ? (
                            <div className="flex flex-col items-center gap-2">
                                <span>No workflows match these filters.</span>
                                <LemonButton type="secondary" size="small" onClick={resetWorkflowFilters}>
                                    Clear filters
                                </LemonButton>
                            </div>
                        ) : (
                            'No workflow runs in this window. Try widening the date range or run scope.'
                        )
                    }
                />

                <div className="text-xs text-tertiary">
                    Pass rate compares successful runs with runs that failed, timed out, failed to start, or became
                    stale. Skipped, canceled, neutral, and action-required runs are excluded. Durations cover successful
                    runs only. Health is workflow-level, not per-job. Workflows that run in the merge queue sort first;
                    the rest are muted.
                    {fleetTruncated && ` Showing the top ${WORKFLOW_HEALTH_LIMIT} workflows by run count.`}
                </div>
            </ScopePanel>
        </div>
    )
}
