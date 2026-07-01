import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils/dateFilters'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BillableBadge } from '../components/BillableBadge'
import { BranchFilter } from '../components/BranchFilter'
import { DistributionBar } from '../components/DistributionBar'
import { RunActivityChart } from '../components/RunActivityChart'
import { RunnerBadge, RunsTable, formatCost } from '../components/runTables'
import { WorkflowHealthHeader } from '../components/WorkflowHealthHeader'
import type { WorkflowRunnerCostApi } from '../generated/api.schemas'
import { githubWorkflowUrl } from '../lib/github'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { WorkflowRunRow, WorkflowRunsLogicProps, workflowRunsLogic } from './workflowRunsLogic'

/** Where a workflow's CI spend goes, split by runner tier — a small table (not bespoke chips) so it reads
 *  like every other table in the product. */
function RunnerCostTable({ costs }: { costs: WorkflowRunnerCostApi[] }): JSX.Element {
    const columns: LemonTableColumns<WorkflowRunnerCostApi> = [
        {
            title: 'Runner',
            key: 'runner',
            render: (_, cost) => <RunnerBadge provider={cost.provider} label={cost.runner_label} />,
        },
        {
            title: 'Jobs',
            key: 'jobs',
            width: 90,
            align: 'right',
            render: (_, cost) => <span className="text-xs tabular-nums">{cost.job_count}</span>,
        },
        {
            title: 'Cost',
            key: 'cost',
            width: 140,
            align: 'right',
            render: (_, cost) => <BillableBadge minutes={cost.billable_minutes} costUsd={cost.estimated_cost_usd} />,
        },
    ]
    // Where the money goes — one stacked bar over the table, a segment per tier sized by its $ share.
    // Free (GitHub-hosted) runners are $0, so they don't take a slice; the bar reads as "billable spend".
    const costSegments = costs.map((cost, i) => ({
        key: `${cost.provider}:${cost.runner_label}`,
        label: cost.runner_label || cost.provider,
        value: cost.estimated_cost_usd ?? 0,
        color: getSeriesColor(i),
        caption: formatCost(cost.estimated_cost_usd ?? null),
    }))
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline gap-2">
                <h3 className="mb-0">Cost by runner</h3>
                <LemonTag type="warning">estimate · wall-clock × reference rate</LemonTag>
            </div>
            <DistributionBar segments={costSegments} />
            <LemonTable
                data-attr="engineering-analytics-workflow-runner-costs"
                size="small"
                columns={columns}
                dataSource={costs}
                rowKey={(cost) => `${cost.provider}:${cost.runner_label}`}
                nouns={['runner tier', 'runner tiers']}
            />
        </div>
    )
}

// The window floors finished runs (the endpoint requires a date_from), so "all time" is out; relative
// windows + Custom only. Covers a CI-health "right now" (24h) through a monthly-ish spend window.
const WORKFLOW_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    [
        'Custom',
        'Last 24 hours',
        'Last 7 days',
        'Last 14 days',
        'Last 30 days',
        'Last 90 days',
        'Last 180 days',
    ].includes(key)
)

export const scene: SceneExport<WorkflowRunsLogicProps> = {
    component: WorkflowRunsScene,
    logic: workflowRunsLogic,
    paramsToProps: ({ params: { repoOwner, repoName, workflowName }, searchParams: { source } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        workflowName: decodeURIComponent(workflowName),
        sourceId: source ?? null,
    }),
}

export function WorkflowRunsScene(): JSX.Element {
    const {
        runRows,
        runsLoading,
        runnerCosts,
        runJobs,
        runJobsLoading,
        expandedRunKeys,
        loadFailed,
        sourceId,
        repoOwner,
        repoName,
        workflowName,
        healthSummary,
        costSummary,
        runsTruncated,
        activityRuns,
        activityTruncated,
    } = useValues(workflowRunsLogic)
    const { loadRuns, setRunExpanded } = useActions(workflowRunsLogic)
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)

    const githubUrl = githubWorkflowUrl(repoOwner, repoName, workflowName)

    // Run id (→ the single-run page) + attempt, branch, attributed PR. The shared RunsTable appends
    // verdict / duration / started and the expand-to-jobs behavior.
    const leadColumns: LemonTableColumns<WorkflowRunRow> = [
        {
            title: 'Run',
            key: 'run',
            render: (_, run) => (
                <Link
                    to={
                        combineUrl(
                            urls.engineeringAnalyticsWorkflowRun(run.repoOwner, run.repoName, run.id),
                            sourceId ? { source: sourceId } : {}
                        ).url
                    }
                    className="font-medium tabular-nums"
                    onClick={(e) => e.stopPropagation()}
                >
                    #{run.id}
                    {(run.runAttempt ?? 1) > 1 && (
                        <span className="ml-1 text-xs text-secondary">· attempt {run.runAttempt}</span>
                    )}
                </Link>
            ),
        },
        {
            title: 'Branch',
            key: 'branch',
            render: (_, run) =>
                run.headBranch ? (
                    <span className="font-mono text-xs">{run.headBranch}</span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'PR',
            key: 'pr',
            width: 80,
            render: (_, run) =>
                run.prNumber > 0 ? (
                    <Link
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsPullRequest(run.repoOwner, run.repoName, run.prNumber),
                                sourceId ? { source: sourceId } : {}
                            ).url
                        }
                        onClick={(e) => e.stopPropagation()}
                    >
                        #{run.prNumber}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
    ]

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Workflow" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this workflow's runs — it may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadRuns} loading={runsLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={workflowName}
                resourceType={{ type: 'health' }}
                actions={
                    <LemonButton type="secondary" size="small" to={githubUrl} targetBlank sideIcon={<IconExternal />}>
                        View on GitHub
                    </LemonButton>
                }
            />
            {/* One window + branch scope the cost breakdown and the runs list below — the same scope as the
                Workflows tab, so numbers match after drilling in (a missing branch filter here read as more
                runs than the tab showed). */}
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold tracking-wide text-secondary uppercase">Window</span>
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                    dateOptions={WORKFLOW_DATE_OPTIONS}
                    size="small"
                />
                <BranchFilter />
            </div>
            <WorkflowHealthHeader summary={healthSummary} cost={costSummary} truncated={runsTruncated} />
            <RunActivityChart runs={activityRuns} truncated={activityTruncated} />
            {runnerCosts.length > 0 && <RunnerCostTable costs={runnerCosts} />}
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Runs</h3>
                <RunsTable
                    runs={runRows}
                    rowKey={(run) => `${run.id}-${run.runAttempt}`}
                    leadColumns={leadColumns}
                    loading={runsLoading}
                    runJobs={runJobs}
                    runJobsLoading={runJobsLoading}
                    expandedKeys={expandedRunKeys}
                    setExpanded={setRunExpanded}
                    // Newest run first on the workflow page.
                    defaultSorting={{ columnKey: 'started', order: -1 }}
                    dataAttr="engineering-analytics-workflow-runs-table"
                    emptyState="No runs for this workflow in the connected source."
                />
            </div>
        </SceneContent>
    )
}

export default WorkflowRunsScene
