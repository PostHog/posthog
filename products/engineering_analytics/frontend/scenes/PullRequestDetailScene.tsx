import { useActions, useValues } from 'kea'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, humanFriendlyDuration, pluralize } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { PullRequestApi } from '../generated/api.schemas'
import { LifecycleSummary, WorkflowRun, isPassingConclusion } from '../lib/lifecycle'
import { PullRequestDetailLogicProps, pullRequestDetailLogic } from './pullRequestDetailLogic'

export const scene: SceneExport<PullRequestDetailLogicProps> = {
    component: PullRequestDetailScene,
    logic: pullRequestDetailLogic,
    paramsToProps: ({ params: { repoOwner, repoName, number } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        number: parseInt(number, 10),
    }),
}

const STATE_TAG: Record<string, { label: string; type: LemonTagType }> = {
    open: { label: 'Open', type: 'primary' },
    merged: { label: 'Merged', type: 'success' },
    closed: { label: 'Closed', type: 'danger' },
}

function verdictTag(conclusion: string | null): { label: string; type: LemonTagType } {
    if (conclusion === null) {
        return { label: 'Running', type: 'warning' }
    }
    const label = capitalizeFirstLetter(conclusion.replace('_', ' '))
    if (conclusion === 'failure' || conclusion === 'timed_out') {
        return { label, type: 'danger' }
    }
    if (isPassingConclusion(conclusion)) {
        return { label, type: conclusion === 'success' ? 'success' : 'muted' }
    }
    return { label, type: 'warning' }
}

function deltaFrom(start: dayjs.Dayjs, end: string): string {
    const seconds = dayjs(end).diff(start, 'second')
    return seconds <= 0 ? '<1s' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

function Milestone({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1 whitespace-nowrap">
            <span className="font-medium">{label}</span>
            <span className="text-secondary">{children}</span>
        </span>
    )
}

/** Chronological — a PR's head-SHA runs can start (and finish) after the merge. */
function LifecycleStrip({ summary, openedAt }: { summary: LifecycleSummary; openedAt: string }): JSX.Element {
    const opened = dayjs(openedAt)
    const dated: { at: string; node: JSX.Element }[] = [
        {
            at: openedAt,
            node: (
                <Milestone label="Opened">
                    <TZLabel time={openedAt} />
                </Milestone>
            ),
        },
    ]
    if (summary.firstCiStartedAt) {
        dated.push({
            at: summary.firstCiStartedAt,
            node: <Milestone label="First CI run">+{deltaFrom(opened, summary.firstCiStartedAt)}</Milestone>,
        })
    }
    if (summary.lastCiFinishedAt) {
        dated.push({
            at: summary.lastCiFinishedAt,
            node: <Milestone label="Last CI verdict">+{deltaFrom(opened, summary.lastCiFinishedAt)}</Milestone>,
        })
    }
    if (summary.mergedAt) {
        dated.push({
            at: summary.mergedAt,
            node: <Milestone label="Merged">+{deltaFrom(opened, summary.mergedAt)}</Milestone>,
        })
    } else if (summary.closedAt) {
        dated.push({
            at: summary.closedAt,
            node: <Milestone label="Closed without merging">+{deltaFrom(opened, summary.closedAt)}</Milestone>,
        })
    }
    dated.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))

    const milestones = dated.map((milestone) => milestone.node)
    if (!summary.mergedAt && !summary.closedAt) {
        milestones.push(
            <Milestone label="Still open">
                {humanFriendlyDuration(dayjs().diff(opened, 'second'), { maxUnits: 2 })} and counting
            </Milestone>
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-surface-primary px-4 py-3 text-sm">
            {milestones.map((node, index) => (
                <span key={index} className="flex items-center gap-3">
                    {index > 0 && <IconArrowRight className="shrink-0 text-tertiary" />}
                    {node}
                </span>
            ))}
        </div>
    )
}

function MetaRow({ pullRequest }: { pullRequest: PullRequestApi }): JSX.Element {
    const stateTag = STATE_TAG[pullRequest.state] ?? { label: pullRequest.state, type: 'muted' as LemonTagType }
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <LemonTag type={stateTag.type}>{stateTag.label}</LemonTag>
            {pullRequest.is_draft && <LemonTag type="muted">draft</LemonTag>}
            <span className="flex items-center gap-1.5">
                {pullRequest.author.avatar_url && (
                    <img src={pullRequest.author.avatar_url} alt="" className="h-5 w-5 shrink-0 rounded-full" />
                )}
                <span>{pullRequest.author.handle}</span>
                {pullRequest.author.is_bot && <LemonTag type="muted">bot</LemonTag>}
            </span>
            <span className="font-mono text-xs text-secondary">
                {pullRequest.repo.owner}/{pullRequest.repo.name} #{pullRequest.number}
            </span>
        </div>
    )
}

export function PullRequestDetailScene(): JSX.Element {
    const { lifecycle, lifecycleLoading, loadFailed, summary, runs } = useValues(pullRequestDetailLogic)
    const { loadLifecycle } = useActions(pullRequestDetailLogic)

    const pullRequest = lifecycle?.pull_request
    const githubUrl = pullRequest
        ? `https://github.com/${pullRequest.repo.owner}/${pullRequest.repo.name}/pull/${pullRequest.number}`
        : null

    const passed = runs.filter((run) => run.conclusion !== null && isPassingConclusion(run.conclusion)).length
    const failed = runs.filter((run) => run.conclusion !== null && !isPassingConclusion(run.conclusion)).length
    const running = runs.filter((run) => run.conclusion === null).length

    const columns: LemonTableColumns<WorkflowRun> = [
        {
            title: 'Workflow',
            key: 'workflow',
            render: (_, run) => <span className="font-medium">{run.workflow}</span>,
        },
        {
            title: 'Verdict',
            key: 'verdict',
            width: 140,
            render: (_, run) => {
                const tag = verdictTag(run.conclusion)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Duration',
            key: 'duration',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.durationSeconds ?? -1) - (b.durationSeconds ?? -1),
            render: (_, run) => (
                <span className="text-xs whitespace-nowrap tabular-nums">
                    {run.durationSeconds == null ? '—' : humanFriendlyDuration(run.durationSeconds)}
                </span>
            ),
        },
        {
            title: 'Finished',
            key: 'finished',
            width: 140,
            align: 'right',
            render: (_, run) =>
                run.finishedAt ? (
                    <span className="text-xs whitespace-nowrap">
                        <TZLabel time={run.finishedAt} />
                    </span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
    ]

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Pull request" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this pull request — it may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadLifecycle} loading={lifecycleLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={pullRequest?.title ?? 'Pull request'}
                resourceType={{ type: 'health' }}
                actions={
                    githubUrl ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={githubUrl}
                            targetBlank
                            sideIcon={<IconExternal />}
                        >
                            View on GitHub
                        </LemonButton>
                    ) : undefined
                }
            />

            {pullRequest ? <MetaRow pullRequest={pullRequest} /> : <LemonSkeleton className="h-5 w-96" />}

            {summary && pullRequest ? (
                <LifecycleStrip summary={summary} openedAt={summary.openedAt ?? pullRequest.created_at} />
            ) : (
                <LemonSkeleton className="h-12 w-full" />
            )}

            <div>
                <div className="mb-2 flex items-baseline justify-between">
                    <h3 className="mb-0">CI runs on the head commit</h3>
                    {runs.length > 0 && (
                        <span className="text-xs text-secondary">
                            {pluralize(passed, 'run')} passed
                            {failed > 0 && <> · {failed} failed</>}
                            {running > 0 && <> · {running} still running</>}
                        </span>
                    )}
                </div>
                <LemonTable
                    data-attr="engineering-analytics-pr-runs-table"
                    size="small"
                    columns={columns}
                    dataSource={runs}
                    rowKey={(run) => `${run.workflow}-${run.startedAt ?? run.finishedAt}`}
                    loading={lifecycleLoading}
                    useURLForSorting={false}
                    emptyState="No CI runs on the head commit yet."
                    nouns={['workflow run', 'workflow runs']}
                />
            </div>

            <div className="text-xs text-tertiary">
                CI events on the head commit only — review and comment activity isn't tracked yet. Runs can start after
                the merge when workflows trigger on the merged commit.
            </div>
        </SceneContent>
    )
}

export default PullRequestDetailScene
