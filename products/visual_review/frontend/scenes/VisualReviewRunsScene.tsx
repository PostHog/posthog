import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconGithub } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RepoSwitcher } from '../components/RepoSwitcher'
import { RunSummaryStats } from '../components/RunSummaryStats'
import { VisualReviewTabs } from '../components/VisualReviewTabs'
import type { RunApi } from '../generated/api.schemas'
import { ReviewState, VisualReviewRunsSceneLogicProps, visualReviewRunsSceneLogic } from './visualReviewRunsSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewRunsScene,
    logic: visualReviewRunsSceneLogic,
    paramsToProps: ({ params: { repoId } }): VisualReviewRunsSceneLogicProps => ({
        repoId: repoId || '',
    }),
}

function BranchCell({ run, repoFullName }: { run: RunApi; repoFullName?: string }): JSX.Element {
    const prUrl = run.pr_number && repoFullName ? `https://github.com/${repoFullName}/pull/${run.pr_number}` : null

    return (
        <div className="flex items-center gap-2 min-w-0">
            {run.pr_number && prUrl ? (
                <Link
                    to={prUrl}
                    target="_blank"
                    className="flex items-center gap-1 text-xs font-medium text-muted hover:text-primary shrink-0"
                    onClick={(e) => e.stopPropagation()}
                    title="Open PR on GitHub"
                >
                    <IconGithub className="text-sm" />#{run.pr_number}
                </Link>
            ) : null}
            <span className="font-medium truncate">{run.branch}</span>
        </div>
    )
}

const EMPTY_MESSAGES: Record<ReviewState, string> = {
    needs_review: 'No runs need review. All caught up!',
    clean: 'No clean runs yet.',
    processing: 'No runs are currently processing.',
    stale: 'No stale runs.',
}

const TAB_COUNT_TYPES: Record<ReviewState, 'warning' | 'highlight' | 'default' | 'muted'> = {
    needs_review: 'warning',
    clean: 'default',
    processing: 'highlight',
    stale: 'muted',
}

export function VisualReviewRunsScene(): JSX.Element {
    const { runs, runsLoading, activeTab, counts, repoId, repoFullName, page, totalCount } =
        useValues(visualReviewRunsSceneLogic)
    const { loadRuns, loadCounts, setActiveTab, setPage } = useActions(visualReviewRunsSceneLogic)

    const columns: LemonTableColumns<RunApi> = [
        {
            title: 'Branch',
            key: 'branch',
            render: (_, run) => <BranchCell run={run} repoFullName={repoFullName} />,
        },
        {
            title: 'Type',
            key: 'run_type',
            width: 90,
            render: (_, run) => (
                <LemonTag type="muted" size="small" className="uppercase">
                    {run.run_type}
                </LemonTag>
            ),
        },
        {
            title: 'Commit',
            key: 'commit',
            width: 90,
            render: (_, run) => <span className="font-mono text-xs text-muted">{run.commit_sha.substring(0, 7)}</span>,
        },
        {
            title: 'Changes',
            key: 'changes',
            width: 140,
            render: (_, run) => <RunSummaryStats summary={run.summary} compact />,
        },
        {
            title: 'Created',
            key: 'created',
            width: 120,
            render: (_, run) => <span className="text-muted">{dayjs(run.created_at).fromNow()}</span>,
        },
        {
            key: 'actions',
            width: 80,
            align: 'right',
            render: (_, run) => {
                const hasChanges = run.summary.changed > 0 || run.summary.new > 0 || run.summary.removed > 0
                const needsReview = run.status === 'completed' && hasChanges && !run.approved

                return (
                    <LemonButton
                        type={needsReview ? 'primary' : 'tertiary'}
                        size="xsmall"
                        onClick={(e) => {
                            e.stopPropagation()
                            router.actions.push(`/visual_review/runs/${run.id}`)
                        }}
                    >
                        {needsReview ? 'Review' : 'View'}
                    </LemonButton>
                )
            },
        },
    ]

    const tabs: { key: ReviewState; label: string }[] = [
        { key: 'needs_review', label: 'Needs review' },
        { key: 'clean', label: 'Clean' },
        { key: 'processing', label: 'Processing' },
        { key: 'stale', label: 'Stale' },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={repoFullName ?? 'Visual review'}
                resourceType={{ type: 'visual_review' }}
                actions={
                    <div className="flex gap-2 items-center">
                        <RepoSwitcher repoId={repoId} activeTab="runs" />
                        <LemonButton size="small" type="secondary" icon={<IconGear />} to={urls.visualReviewSettings()}>
                            Settings
                        </LemonButton>
                    </div>
                }
            />
            <VisualReviewTabs activeKey="runs" repoId={repoId} />

            <div className="mb-3 flex items-center gap-2">
                <LemonSegmentedButton
                    value={activeTab}
                    onChange={(value) => setActiveTab(value)}
                    options={tabs.map(({ key, label }) => ({
                        value: key,
                        label: (
                            <span className="flex items-center gap-1.5">
                                {label}
                                {(key === 'needs_review' || key === 'processing') && counts[key] > 0 && (
                                    <LemonTag type={TAB_COUNT_TYPES[key]} size="small">
                                        {counts[key]}
                                    </LemonTag>
                                )}
                            </span>
                        ),
                    }))}
                    size="small"
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => {
                        loadRuns()
                        loadCounts()
                    }}
                    loading={runsLoading}
                    // Push refresh away from the segmented filter; sitting flush
                    // next to the active-tab handle made it look like another tab.
                    className="ml-auto"
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonTable
                dataSource={runs}
                columns={columns}
                loading={runsLoading}
                pagination={{
                    controlled: true,
                    pageSize: 20,
                    currentPage: page,
                    entryCount: totalCount,
                    onBackward: () => setPage(page - 1),
                    onForward: () => setPage(page + 1),
                }}
                nouns={['run', 'runs']}
                emptyState={EMPTY_MESSAGES[activeTab]}
                onRow={(run) => ({
                    onClick: () => router.actions.push(`/visual_review/runs/${run.id}`),
                    className: 'cursor-pointer',
                })}
            />
        </SceneContent>
    )
}

export default VisualReviewRunsScene
