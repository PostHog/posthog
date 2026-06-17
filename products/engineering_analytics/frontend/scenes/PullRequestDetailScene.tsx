import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconExternal } from '@posthog/icons'
import {
    LemonButton,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { PullRequestApi } from '../generated/api.schemas'
import { githubPrUrl, githubRunUrl, githubWorkflowUrl } from '../lib/github'
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

function gapBetween(from: string, to: string): string {
    const seconds = dayjs(to).diff(dayjs(from), 'second')
    return seconds <= 0 ? '<1s' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

interface TimelineNode {
    key: string
    label: string
    at: string
    dotClass: string
    /** The connector leading into this node — dashed when the time span is still running. */
    dashedIncoming?: boolean
    showTime?: boolean
}

/**
 * Horizontal timeline: dots are milestones, the duration above each connector is the
 * gap between them — where the hours actually went. Chronological — a PR's head-SHA
 * runs can start (and finish) after the merge.
 */
function LifecycleStrip({ summary, openedAt }: { summary: LifecycleSummary; openedAt: string }): JSX.Element {
    const nodes: TimelineNode[] = [
        { key: 'opened', label: 'Opened', at: openedAt, dotClass: 'bg-muted', showTime: true },
    ]
    if (summary.firstCiStartedAt) {
        nodes.push({
            key: 'ci-start',
            label: 'First CI run',
            at: summary.firstCiStartedAt,
            dotClass: 'bg-muted',
        })
    }
    if (summary.lastCiFinishedAt) {
        nodes.push({
            key: 'ci-end',
            label: 'Last CI verdict',
            at: summary.lastCiFinishedAt,
            dotClass: 'bg-muted',
        })
    }
    if (summary.mergedAt) {
        nodes.push({ key: 'merged', label: 'Merged', at: summary.mergedAt, dotClass: 'bg-success', showTime: true })
    } else if (summary.closedAt) {
        nodes.push({ key: 'closed', label: 'Closed', at: summary.closedAt, dotClass: 'bg-danger', showTime: true })
    }
    nodes.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))

    const stillOpen = !summary.mergedAt && !summary.closedAt
    if (stillOpen) {
        nodes.push({
            key: 'now',
            label: 'Still open',
            at: dayjs().toISOString(),
            dotClass: 'animate-pulse border-2 border-warning bg-transparent',
            dashedIncoming: true,
        })
    }

    // Not necessarily the last node's time: head-SHA runs can outlive the merge.
    const totalTo = summary.mergedAt ?? summary.closedAt ?? nodes[nodes.length - 1].at
    const connector = (dashed: boolean | undefined): string =>
        dashed ? 'w-full border-t border-dashed border-border-bold' : 'h-px w-full bg-border-bold'

    return (
        <div className="flex items-center gap-6 rounded-lg border bg-surface-primary px-5 py-3">
            <div className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
                {nodes.map((node, index) => (
                    <Fragment key={node.key}>
                        {index > 0 && (
                            <div className="flex min-w-10 flex-1 flex-col gap-1">
                                <span className="text-center text-xs leading-4 whitespace-nowrap text-secondary tabular-nums">
                                    {gapBetween(nodes[index - 1].at, node.at)}
                                </span>
                                <span className="flex h-2.5 items-center">
                                    <span className={connector(node.dashedIncoming)} />
                                </span>
                                <span className="text-xs leading-4">&nbsp;</span>
                            </div>
                        )}
                        <div className="flex shrink-0 flex-col items-center gap-1 px-1">
                            <span className="text-xs font-medium leading-4 whitespace-nowrap">{node.label}</span>
                            <span className="flex h-2.5 w-full items-center">
                                <span className={cn('flex-1', index > 0 && connector(node.dashedIncoming))} />
                                <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', node.dotClass)} />
                                <span
                                    className={cn(
                                        'flex-1',
                                        index < nodes.length - 1 && connector(nodes[index + 1].dashedIncoming)
                                    )}
                                />
                            </span>
                            <span className="text-xs leading-4 whitespace-nowrap text-tertiary">
                                {node.showTime ? <TZLabel time={node.at} /> : <>&nbsp;</>}
                            </span>
                        </div>
                    </Fragment>
                ))}
            </div>
            <div className="flex shrink-0 flex-col items-end self-center border-l border-primary pl-6">
                <span className="text-lg font-semibold leading-6 tabular-nums">{gapBetween(openedAt, totalTo)}</span>
                <span className="text-xs text-tertiary">
                    {summary.mergedAt ? 'open → merge' : summary.closedAt ? 'open → close' : 'open so far'}
                </span>
            </div>
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
        ? githubPrUrl(pullRequest.repo.owner, pullRequest.repo.name, pullRequest.number)
        : null

    const passed = runs.filter((run) => run.conclusion !== null && isPassingConclusion(run.conclusion)).length
    const failed = runs.filter((run) => run.conclusion !== null && !isPassingConclusion(run.conclusion)).length
    const running = runs.filter((run) => run.conclusion === null).length

    const columns: LemonTableColumns<WorkflowRun> = [
        {
            title: 'Workflow',
            key: 'workflow',
            render: (_, run) =>
                pullRequest ? (
                    <Link
                        to={
                            run.runId != null
                                ? githubRunUrl(pullRequest.repo.owner, pullRequest.repo.name, run.runId)
                                : githubWorkflowUrl(pullRequest.repo.owner, pullRequest.repo.name, run.workflow)
                        }
                        target="_blank"
                        className="font-medium"
                    >
                        {run.workflow}
                    </Link>
                ) : (
                    <span className="font-medium">{run.workflow}</span>
                ),
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
