import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { WorkflowRunDetailApi } from '../generated/api.schemas'
import { githubWorkflowUrl } from '../lib/github'
import { verdictTag } from '../lib/runStatus'
import { WorkflowRunsLogicProps, workflowRunsLogic } from './workflowRunsLogic'

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
    const { runs, runsLoading, loadFailed, sourceId, repoOwner, repoName, workflowName } = useValues(workflowRunsLogic)
    const { loadRuns } = useActions(workflowRunsLogic)

    const githubUrl = githubWorkflowUrl(repoOwner, repoName, workflowName)

    const columns: LemonTableColumns<WorkflowRunDetailApi> = [
        {
            title: 'Run',
            key: 'run',
            render: (_, run) => (
                <Link
                    to={
                        combineUrl(
                            urls.engineeringAnalyticsWorkflowRun(run.repo.owner, run.repo.name, run.id),
                            sourceId ? { source: sourceId } : {}
                        ).url
                    }
                    className="font-medium tabular-nums"
                >
                    #{run.id}
                    {run.run_attempt > 1 && (
                        <span className="ml-1 text-xs text-secondary">· attempt {run.run_attempt}</span>
                    )}
                </Link>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 120,
            render: (_, run) => {
                const tag = verdictTag(run.conclusion)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Branch',
            key: 'branch',
            render: (_, run) =>
                run.head_branch ? (
                    <span className="font-mono text-xs">{run.head_branch}</span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'PR',
            key: 'pr',
            width: 80,
            render: (_, run) =>
                run.pr_number > 0 ? (
                    <Link
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsPullRequest(run.repo.owner, run.repo.name, run.pr_number),
                                sourceId ? { source: sourceId } : {}
                            ).url
                        }
                    >
                        #{run.pr_number}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Duration',
            key: 'duration',
            width: 120,
            align: 'right',
            sorter: (a, b) => (a.duration_seconds ?? -1) - (b.duration_seconds ?? -1),
            render: (_, run) => (
                <span className="text-xs whitespace-nowrap tabular-nums">
                    {run.duration_seconds == null ? '—' : humanFriendlyDuration(run.duration_seconds)}
                </span>
            ),
        },
        {
            title: 'Started',
            key: 'started',
            width: 140,
            align: 'right',
            render: (_, run) =>
                run.run_started_at ? (
                    <span className="text-xs whitespace-nowrap">
                        <TZLabel time={run.run_started_at} />
                    </span>
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
            <LemonTable
                data-attr="engineering-analytics-workflow-runs-table"
                size="small"
                columns={columns}
                dataSource={runs}
                rowKey={(run) => `${run.id}-${run.run_attempt}`}
                loading={runsLoading}
                useURLForSorting={false}
                pagination={{ pageSize: 50 }}
                emptyState="No runs for this workflow in the connected source."
                nouns={['run', 'runs']}
            />
        </SceneContent>
    )
}

export default WorkflowRunsScene
