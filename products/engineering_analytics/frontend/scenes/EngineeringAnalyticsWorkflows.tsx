import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { WorkflowsHealthHeader } from '../components/WorkflowsHealthHeader'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

// The endpoint caps the window at 366 days, so "All time" and week/month snaps are out.
const WORKFLOW_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    [
        'Custom',
        'Last 24 hours',
        'Last 7 days',
        'Last 14 days',
        'Last 30 days',
        'Last 90 days',
        'Last 180 days',
        'Year to date',
    ].includes(key)
)

export function EngineeringAnalyticsWorkflows(): JSX.Element {
    const {
        workflowHealth,
        workflowHealthLoading,
        notConnected,
        workflowHealthLoadError,
        workflowDateFrom,
        workflowDateTo,
        branchInput,
        appliedBranch,
        sourceId,
        fleetSummary,
        fleetTruncated,
    } = useValues(engineeringAnalyticsLogic)
    const { setWorkflowDateRange, setBranchFilter, applyBranchFilter, refresh } = useActions(engineeringAnalyticsLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (workflowHealthLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    const windowLabel = dateFilterToText(workflowDateFrom, workflowDateTo, 'Last 24 hours') ?? 'Last 24 hours'

    // Stage + apply a branch in one click (the chips). Clicking the active chip clears back to all branches.
    const selectBranch = (branch: string): void => {
        setBranchFilter(branch)
        applyBranchFilter()
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
                <DateFilter
                    dateFrom={workflowDateFrom}
                    dateTo={workflowDateTo}
                    onChange={setWorkflowDateRange}
                    dateOptions={WORKFLOW_DATE_OPTIONS}
                />
                <LemonInput
                    type="search"
                    size="small"
                    className="w-56"
                    placeholder="Branch: all (e.g. main)"
                    value={branchInput}
                    onChange={setBranchFilter}
                    onPressEnter={applyBranchFilter}
                    onBlur={applyBranchFilter}
                    data-attr="engineering-analytics-branch-filter"
                />
                {/* Quick presets for the default branch. We can't tell main from master without another query,
                    so offer both — clicking the active one clears back to all branches. */}
                {['main', 'master'].map((branch) => (
                    <LemonButton
                        key={branch}
                        size="xsmall"
                        type={appliedBranch === branch ? 'primary' : 'secondary'}
                        onClick={() => selectBranch(appliedBranch === branch ? '' : branch)}
                    >
                        {branch}
                    </LemonButton>
                ))}
            </div>
            {workflowHealth.length > 0 && <WorkflowsHealthHeader summary={fleetSummary} truncated={fleetTruncated} />}
            <WorkflowHealthTable
                rows={workflowHealth}
                loading={workflowHealthLoading}
                sourceId={sourceId}
                showCost={workflowHealth.some((row) => row.billableMinutes != null || row.estimatedCostUsd != null)}
                emptyState={
                    appliedBranch
                        ? `No workflow runs on '${appliedBranch}' in this window.`
                        : 'No workflow runs in this window.'
                }
            />
            <div className="text-xs text-tertiary">
                Success rate and durations are computed over completed runs only — a run that hasn't settled is
                excluded, not counted as a failure. Window: {windowLabel}
                {appliedBranch ? ` · branch: ${appliedBranch}` : ''}.
            </div>
        </div>
    )
}
