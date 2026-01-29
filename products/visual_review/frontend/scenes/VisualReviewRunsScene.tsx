import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconGithub } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs, Spinner } from '@posthog/lemon-ui'

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

function RunCard({ run, repoFullName }: { run: RunApi; repoFullName?: string }): JSX.Element {
    const hasChanges = run.summary.changed > 0 || run.summary.new > 0 || run.summary.removed > 0
    const isProcessing = run.status === 'pending' || run.status === 'processing'
    const prUrl = run.pr_number && repoFullName ? `https://github.com/${repoFullName}/pull/${run.pr_number}` : null

    return (
        <div
            className="bg-bg-light border rounded-lg p-4 hover:border-primary cursor-pointer transition-colors flex flex-col"
            onClick={() => router.actions.push(`/visual_review/runs/${run.id}`)}
        >
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                    {run.pr_number ? (
                        <span
                            className="flex items-center gap-1 text-xs font-medium text-muted bg-bg-3000 px-1.5 py-0.5 rounded shrink-0"
                            onClick={(e) => {
                                if (prUrl) {
                                    e.stopPropagation()
                                    window.open(prUrl, '_blank')
                                }
                            }}
                            title={prUrl ? 'Open PR on GitHub' : undefined}
                        >
                            <IconGithub className="text-sm" />#{run.pr_number}
                        </span>
                    ) : null}
                    <span className="font-semibold truncate">{run.branch}</span>
                </div>
                <span className="font-mono text-xs text-muted shrink-0">{run.commit_sha.substring(0, 7)}</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted mb-3">
                <RunStatusBadge status={run.status} />
                {run.approved && <span className="text-success text-xs font-medium">Approved</span>}
                <span className="ml-auto">{dayjs(run.created_at).fromNow()}</span>
            </div>
            <div className="flex items-center justify-between mt-auto pt-2 border-t border-border-light">
                <RunSummaryStats summary={run.summary} />
                {isProcessing ? (
                    <Spinner className="text-lg" />
                ) : hasChanges && !run.approved ? (
                    <LemonButton type="primary" size="small">
                        Review
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" size="small">
                        View
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function RunCardSkeleton(): JSX.Element {
    return (
        <div className="bg-bg-light border rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                    <LemonSkeleton className="h-5 w-48 mb-2" />
                    <LemonSkeleton className="h-4 w-32" />
                </div>
                <LemonSkeleton className="h-8 w-24" />
            </div>
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

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
                {runsLoading && filteredRuns.length === 0 ? (
                    <>
                        <RunCardSkeleton />
                        <RunCardSkeleton />
                        <RunCardSkeleton />
                        <RunCardSkeleton />
                    </>
                ) : filteredRuns.length === 0 ? (
                    <div className="col-span-full text-center py-12 text-muted">{emptyMessages[activeTab]}</div>
                ) : (
                    filteredRuns.map((run) => <RunCard key={run.id} run={run} repoFullName={repoFullName} />)
                )}
            </div>
        </SceneContent>
    )
}

export default VisualReviewRunsScene
