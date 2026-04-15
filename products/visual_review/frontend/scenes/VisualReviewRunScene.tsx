import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SnapshotDiffViewer } from '../components/SnapshotDiffViewer'
import { SnapshotStatusIndicator } from '../components/SnapshotStatusIndicator'
import type { SnapshotApi } from '../generated/api.schemas'
import { VisualReviewRunSceneLogicProps, visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewRunScene,
    logic: visualReviewRunSceneLogic,
    paramsToProps: ({ params: { runId } }): VisualReviewRunSceneLogicProps => ({
        runId: runId || '',
    }),
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

    return (
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
                    <img src={snapshot.current_artifact.download_url} alt="" className="w-full h-full object-contain" />
                ) : (
                    <div className="w-full h-full flex items-center justify-center">
                        <span className="text-[10px] text-muted">No image</span>
                    </div>
                )}
            </div>
            <div className="flex items-center gap-1 max-w-[108px]">
                <SnapshotStatusIndicator
                    result={snapshot.result || 'unchanged'}
                    reviewState={snapshot.review_state}
                    classificationReason={snapshot.classification_reason}
                    compact
                />
                <span className={`text-[11px] truncate ${isSelected ? 'font-medium' : 'text-muted'}`}>{shortName}</span>
            </div>
        </button>
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

    // Review summary (from loaded snapshots — paginated but covers actionable ones first)
    const reviewPending = snapshots.filter(
        (s: SnapshotApi) => s.result !== 'unchanged' && s.review_state === 'pending'
    ).length
    const reviewApproved = snapshots.filter((s: SnapshotApi) => s.review_state === 'approved').length
    const reviewTolerated = snapshots.filter((s: SnapshotApi) => s.review_state === 'tolerated').length

    // Diff summary (server-side counts, subtract human-tolerated to avoid double counting)
    const diffChanged = run.summary.changed
    const diffNew = run.summary.new
    const diffRemoved = run.summary.removed
    const autoTolerated = Math.max(0, (run.summary.tolerated_matched ?? 0) - reviewTolerated)

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
                    <div className="flex items-center justify-between px-3 pt-3 pb-2">
                        {/* Review summary (left) — what humans decided */}
                        <span className="text-xs text-muted flex items-center gap-1.5">
                            <span className="font-semibold text-default">Review</span>
                            {[
                                reviewPending > 0 && (
                                    <span key="pend">
                                        <span className="font-semibold">{reviewPending}</span>
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
                                .reduce<React.ReactNode[]>((acc, el, i) => (i === 0 ? [el] : [...acc, ' · ', el]), [])}
                        </span>
                        {/* Diff summary (right) — what the system found */}
                        <span className="text-xs text-muted flex items-center gap-1.5">
                            <span className="font-semibold text-default">Diff</span>
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
                                autoTolerated > 0 && <span key="tol">{autoTolerated} auto-tolerated</span>,
                            ]
                                .filter(Boolean)
                                .reduce<React.ReactNode[]>((acc, el, i) => (i === 0 ? [el] : [...acc, ' · ', el]), [])}
                        </span>
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
