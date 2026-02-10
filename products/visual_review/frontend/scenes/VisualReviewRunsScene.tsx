import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconGithub } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTabs, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RunStatusBadge } from '../components/RunStatusBadge'
import { RunSummaryStats } from '../components/RunSummaryStats'
import type { RunApi } from '../generated/api.schemas'
import { RunFilterTab, visualReviewRunsSceneLogic } from './visualReviewRunsSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewRunsScene,
    logic: visualReviewRunsSceneLogic,
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

export function VisualReviewRunsScene(): JSX.Element {
    const { filteredRuns, runsLoading, activeTab, tabCounts, repoFullName } = useValues(visualReviewRunsSceneLogic)
    const { loadRuns, setActiveTab } = useActions(visualReviewRunsSceneLogic)

    const emptyMessages: Record<RunFilterTab, string> = {
        needs_review: 'No runs need review. All caught up!',
        clean: 'No clean runs yet.',
        processing: 'No runs are currently processing.',
    }

    const columns: LemonTableColumns<RunApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 120,
            render: (_, run) => (
                <div className="flex items-center gap-2">
                    <RunStatusBadge status={run.status} />
                    {run.approved && <span className="text-success text-xs font-medium">✓</span>}
                </div>
            ),
        },
        {
            title: 'Branch',
            key: 'branch',
            render: (_, run) => <BranchCell run={run} repoFullName={repoFullName} />,
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

    return (
        <SceneContent>
            <SceneTitleSection
                name="Visual review"
                resourceType={{ type: 'visual_review' }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="secondary" icon={<IconGear />} to="/visual_review/settings">
                            Settings
                        </LemonButton>
                        <LemonButton type="secondary" onClick={loadRuns} loading={runsLoading}>
                            Refresh
                        </LemonButton>
                    </div>
                }
            />

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                tabs={[
                    {
                        key: 'needs_review' as RunFilterTab,
                        label: (
                            <span>
                                Needs review
                                {tabCounts.needs_review > 0 && (
                                    <span className="ml-1.5 px-1.5 py-0.5 text-xs rounded-full bg-warning-highlight text-warning-dark">
                                        {tabCounts.needs_review}
                                    </span>
                                )}
                            </span>
                        ),
                    },
                    {
                        key: 'clean' as RunFilterTab,
                        label: (
                            <span>
                                Clean
                                {tabCounts.clean > 0 && (
                                    <span className="ml-1.5 px-1.5 py-0.5 text-xs rounded-full bg-success-highlight text-success-dark">
                                        {tabCounts.clean}
                                    </span>
                                )}
                            </span>
                        ),
                    },
                    {
                        key: 'processing' as RunFilterTab,
                        label: (
                            <span>
                                Processing
                                {tabCounts.processing > 0 && (
                                    <span className="ml-1.5 px-1.5 py-0.5 text-xs rounded-full bg-muted-alt text-muted">
                                        {tabCounts.processing}
                                    </span>
                                )}
                            </span>
                        ),
                    },
                ]}
            />

            <LemonTable
                dataSource={filteredRuns}
                columns={columns}
                loading={runsLoading}
                pagination={{ pageSize: 20 }}
                nouns={['run', 'runs']}
                emptyState={emptyMessages[activeTab]}
                onRow={(run) => ({
                    onClick: () => router.actions.push(`/visual_review/runs/${run.id}`),
                    className: 'cursor-pointer',
                })}
            />
        </SceneContent>
    )
}

export default VisualReviewRunsScene
