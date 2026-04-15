import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SnapshotDiffViewer } from '../components/SnapshotDiffViewer'
import type { SnapshotApi } from '../generated/api.schemas'
import { VisualReviewRunSceneLogicProps, visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewRunScene,
    logic: visualReviewRunSceneLogic,
    paramsToProps: ({ params: { runId } }): VisualReviewRunSceneLogicProps => ({
        runId: runId || '',
    }),
}

const RESULT_DOT_COLORS: Record<string, string> = {
    changed: 'bg-warning',
    new: 'bg-primary',
    removed: 'bg-danger',
    unchanged: 'bg-muted',
}

const REVIEW_STATE_ICONS: Record<string, { symbol: string; color: string } | null> = {
    approved: { symbol: '✓', color: 'text-success' },
    tolerated: { symbol: '~', color: 'text-muted' },
    pending: null,
}

function SnapshotThumbnail({
    snapshot,
    isSelected,
    onClick,
}: {
    snapshot: SnapshotApi
    isSelected: boolean
    onClick: () => void
}): JSX.Element {
    const parts = snapshot.identifier.split('--')
    const shortName = parts.length > 1 ? parts[parts.length - 1] : parts[0]
    const result = snapshot.result || 'unchanged'
    const reviewIcon = REVIEW_STATE_ICONS[snapshot.review_state]

    return (
        <Tooltip title={snapshot.identifier}>
            <button
                type="button"
                onClick={onClick}
                className="flex flex-col items-center gap-1 shrink-0 rounded p-1.5 transition-colors"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    background: isSelected ? 'var(--primary-3000-button-bg)' : 'transparent',
                    border: '1.5px solid',
                    borderColor: isSelected ? 'var(--primary-3000-button-border)' : 'var(--border)',
                    boxShadow: isSelected ? '0 3px 0 -1px var(--primary-3000-frame-bg)' : 'none',
                }}
            >
                <div className="w-[104px] h-[72px] rounded-sm overflow-hidden bg-bg-3000">
                    {snapshot.current_artifact?.download_url ? (
                        <img
                            src={snapshot.current_artifact.download_url}
                            alt=""
                            className="w-full h-full object-contain"
                        />
                    ) : (
                        <div className="w-full h-full flex items-center justify-center">
                            <span className="text-[10px] text-muted">No image</span>
                        </div>
                    )}
                </div>
                <div className="flex items-center gap-1 max-w-[108px]">
                    <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${RESULT_DOT_COLORS[result] || 'bg-muted'}`} />
                    <span className={`text-[11px] truncate ${isSelected ? 'font-medium' : 'text-muted'}`}>
                        {shortName}
                    </span>
                    {reviewIcon && (
                        <span className={`text-[10px] shrink-0 ${reviewIcon.color}`}>{reviewIcon.symbol}</span>
                    )}
                </div>
            </button>
        </Tooltip>
    )
}

export function VisualReviewRunScene(): JSX.Element {
    const {
        run,
        runLoading,
        snapshots,
        snapshotsLoading,
        selectedSnapshot,
        changedSnapshots,
        snapshotHistory,
        snapshotHistoryLoading,
        toleratedHashes,
        toleratedHashesLoading,
        repoFullName,
    } = useValues(visualReviewRunSceneLogic)
    const { setSelectedSnapshotId, approveChanges, approveSnapshot, markAsTolerated } =
        useActions(visualReviewRunSceneLogic)

    if (runLoading || !run) {
        return (
            <SceneContent>
                <div className="space-y-4 py-4">
                    <LemonSkeleton className="h-8 w-1/3" />
                    <div className="flex gap-2">
                        <LemonSkeleton className="h-6 w-20" />
                        <LemonSkeleton className="h-6 w-16" />
                        <LemonSkeleton className="h-6 w-16" />
                    </div>
                    <LemonSkeleton className="h-24 w-full" />
                    <LemonSkeleton className="h-64 w-full" />
                </div>
            </SceneContent>
        )
    }

    // Diff summary (server-side counts are accurate, client-side for review states)
    const diffChanged = run.summary.changed
    const diffNew = run.summary.new
    const diffRemoved = run.summary.removed
    const autoTolerated = run.summary.tolerated_matched ?? 0

    // Review summary (from loaded snapshots — paginated but covers actionable ones first)
    const reviewPending = snapshots.filter(
        (s: SnapshotApi) => s.result !== 'unchanged' && s.review_state === 'pending'
    ).length
    const reviewApproved = snapshots.filter((s: SnapshotApi) => s.review_state === 'approved').length
    const reviewTolerated = snapshots.filter((s: SnapshotApi) => s.review_state === 'tolerated').length

    // If server counts are higher than loaded, show "+" to hint at pagination
    const totalActionable = diffChanged + diffNew + diffRemoved
    const loadedActionable = reviewPending + reviewApproved + reviewTolerated
    const hasMore = totalActionable > loadedActionable

    // Navigation — use changed snapshots when there are changes, otherwise all snapshots
    const navSnapshots = changedSnapshots.length > 0 ? changedSnapshots : snapshots
    const currentIndex = selectedSnapshot
        ? navSnapshots.findIndex((s: SnapshotApi) => s.id === selectedSnapshot.id)
        : -1
    const hasPrevious = currentIndex > 0
    const hasNext = currentIndex >= 0 && currentIndex < navSnapshots.length - 1

    const goToPrevious = (): void => {
        if (hasPrevious) {
            setSelectedSnapshotId(navSnapshots[currentIndex - 1].id)
        }
    }

    const goToNext = (): void => {
        if (hasNext) {
            setSelectedSnapshotId(navSnapshots[currentIndex + 1].id)
        }
    }

    const handleApproveSnapshot = (): void => {
        if (selectedSnapshot) {
            approveSnapshot(selectedSnapshot)
        }
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={run.branch}
                resourceType={{ type: 'visual_review' }}
                actions={
                    !run.approved && reviewPending > 0 ? (
                        <LemonButton type="primary" onClick={approveChanges}>
                            Approve all changes
                        </LemonButton>
                    ) : undefined
                }
            />

            {/* Snapshots panel — thumbnail strip as nav, diff viewer as body */}
            <div className="border rounded-lg overflow-hidden">
                {/* Header: summary + thumbnail strip */}
                <div className="bg-bg-light border-b">
                    <div className="px-3 pt-3 pb-2 space-y-1">
                        {/* Diff summary — what the system found */}
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">Diff</span>
                            <span className="text-xs text-muted">
                                {[
                                    diffChanged > 0 && (
                                        <span key="ch" className="text-warning-dark">
                                            {diffChanged} changed
                                        </span>
                                    ),
                                    diffNew > 0 && (
                                        <span key="new" className="text-primary-dark">
                                            {diffNew} added
                                        </span>
                                    ),
                                    diffRemoved > 0 && (
                                        <span key="rm" className="text-danger">
                                            {diffRemoved} removed
                                        </span>
                                    ),
                                    autoTolerated > 0 && (
                                        <span key="tol" className="text-muted">
                                            {autoTolerated} auto-tolerated
                                        </span>
                                    ),
                                ]
                                    .filter(Boolean)
                                    .reduce<React.ReactNode[]>(
                                        (acc, el, i) => (i === 0 ? [el] : [...acc, ' · ', el]),
                                        []
                                    )}
                            </span>
                        </div>
                        {/* Review summary — what humans decided */}
                        {(reviewPending > 0 || reviewApproved > 0 || reviewTolerated > 0) && (
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold">Review</span>
                                <span className="text-xs text-muted">
                                    {[
                                        reviewPending > 0 && (
                                            <span key="pend">
                                                {reviewPending}
                                                {hasMore ? '+' : ''} pending
                                            </span>
                                        ),
                                        reviewApproved > 0 && (
                                            <span key="appr" className="text-success">
                                                {reviewApproved} approved
                                            </span>
                                        ),
                                        reviewTolerated > 0 && <span key="tol">{reviewTolerated} tolerated</span>,
                                    ]
                                        .filter(Boolean)
                                        .reduce<React.ReactNode[]>(
                                            (acc, el, i) => (i === 0 ? [el] : [...acc, ' · ', el]),
                                            []
                                        )}
                                </span>
                            </div>
                        )}
                    </div>

                    {navSnapshots.length > 0 && (
                        <div className="flex gap-1.5 overflow-x-auto px-3 pb-3">
                            {navSnapshots.map((snapshot: SnapshotApi) => (
                                <SnapshotThumbnail
                                    key={snapshot.id}
                                    snapshot={snapshot}
                                    isSelected={selectedSnapshot?.id === snapshot.id}
                                    onClick={() => setSelectedSnapshotId(snapshot.id)}
                                />
                            ))}
                        </div>
                    )}
                </div>

                {/* Body: diff viewer */}
                <div className="p-4">
                    {selectedSnapshot ? (
                        <SnapshotDiffViewer
                            snapshot={selectedSnapshot}
                            snapshotHistory={snapshotHistory}
                            snapshotHistoryLoading={snapshotHistoryLoading}
                            toleratedHashes={toleratedHashes}
                            toleratedHashesLoading={toleratedHashesLoading}
                            onApprove={handleApproveSnapshot}
                            onMarkTolerated={() => markAsTolerated(selectedSnapshot)}
                            onPrevious={goToPrevious}
                            onNext={goToNext}
                            hasPrevious={hasPrevious}
                            hasNext={hasNext}
                            currentIndex={currentIndex >= 0 ? currentIndex : undefined}
                            totalCount={navSnapshots.length}
                            commitSha={run.commit_sha}
                            prNumber={run.pr_number}
                            repoFullName={repoFullName}
                        />
                    ) : snapshotsLoading ? (
                        <div className="space-y-3 py-4">
                            <LemonSkeleton className="h-6 w-1/4" />
                            <LemonSkeleton className="h-48 w-full" />
                        </div>
                    ) : changedSnapshots.length > 0 ? (
                        <div className="text-center text-muted py-8">Select a snapshot to view details</div>
                    ) : (
                        <div className="text-center text-muted py-8">No visual changes in this run</div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

export default VisualReviewRunScene
