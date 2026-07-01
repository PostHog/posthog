import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'

import { BranchFilter } from '../components/BranchFilter'
import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { WorkflowsHealthHeader } from '../components/WorkflowsHealthHeader'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
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
        sourceId,
        fleetSummary,
        fleetTruncated,
    } = useValues(engineeringAnalyticsLogic)
    const { refresh } = useActions(engineeringAnalyticsLogic)
    const { dateFrom, dateTo, appliedBranch } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (workflowHealthLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    const windowLabel = dateFilterToText(dateFrom, dateTo, 'Last 7 days') ?? 'Last 7 days'

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                    dateOptions={WORKFLOW_DATE_OPTIONS}
                />
                <BranchFilter />
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
