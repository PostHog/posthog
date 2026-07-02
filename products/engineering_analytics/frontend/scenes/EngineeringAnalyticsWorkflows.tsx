// The fleet-level workflow list page — the full surface behind the hub's capped workflows section,
// the CI sibling of the Pull requests tab. Skeleton: scope bar → fleet verdict header → controls →
// table → caveats. Every row opens the workflow page, one level down.

import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { WorkflowsHealthHeader } from '../components/WorkflowsHealthHeader'
import { WORKFLOW_HEALTH_LIMIT, WorkflowStatusFilter, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

export function EngineeringAnalyticsWorkflows(): JSX.Element {
    const {
        fleetSummary,
        fleetTruncated,
        filteredWorkflowHealth,
        workflowHealthLoading,
        workflowSearch,
        workflowStatusFilter,
        hasActiveWorkflowFilters,
        workflowCostAvailable,
        sourceId,
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
            <ScopeBar repoSlot={<SourceScopeChip />} showBranch />

            <WorkflowsHealthHeader summary={fleetSummary} truncated={fleetTruncated} />

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
                defaultSorting={{ columnKey: 'runCount', order: -1 }}
                emptyState={
                    hasActiveWorkflowFilters ? (
                        <div className="flex flex-col items-center gap-2">
                            <span>No workflows match these filters.</span>
                            <LemonButton type="secondary" size="small" onClick={resetWorkflowFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ) : (
                        'No workflow runs in this window — widen the date range or branch scope.'
                    )
                }
            />

            <div className="text-xs text-tertiary">
                Pass rate and durations are over completed runs only — a run that hasn't settled is excluded, never
                counted as a failure. Health is workflow-level, not per-job.
                {fleetTruncated && ` Showing the top ${WORKFLOW_HEALTH_LIMIT} workflows by run count.`}
            </div>
        </div>
    )
}
