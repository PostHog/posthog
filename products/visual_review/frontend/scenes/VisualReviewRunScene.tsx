import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { DetectiveHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
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
    isQuarantined,
    onClick,
}: {
    snapshot: SnapshotApi
    isSelected: boolean
    isQuarantined: boolean
    onClick: () => void
}): JSX.Element {
    const parts = snapshot.identifier.split('--')
    const theme = parts[parts.length - 1]
    const isTheme = theme === 'dark' || theme === 'light'
    const shortName = parts.length > 1 ? parts.slice(1, isTheme ? -1 : undefined).join(' · ') : snapshot.identifier

    const [imageLoaded, setImageLoaded] = useState(false)
    const isReviewed = snapshot.review_state === 'approved' || snapshot.review_state === 'tolerated'
    const showBadge = isReviewed || isQuarantined
    const hasDiff = snapshot.diff_percentage != null && snapshot.diff_percentage > 0

    return (
        <button
            type="button"
            onClick={onClick}
            className="relative flex flex-col items-center gap-1 shrink-0 rounded overflow-hidden p-1.5 transition-colors"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                background: isSelected ? 'var(--primary-3000-button-bg)' : 'transparent',
                border: '1.5px solid',
                borderColor: isSelected ? 'var(--primary-3000-button-border)' : 'var(--border)',
                boxShadow: isSelected ? '0 3px 0 -1px var(--primary-3000-frame-bg)' : 'none',
            }}
        >
            {showBadge && (
                <>
                    <span
                        className={`absolute top-0 right-0 w-7 h-7 z-10 ${
                            isQuarantined
                                ? 'bg-warning'
                                : snapshot.review_state === 'approved'
                                  ? 'bg-success'
                                  : 'bg-muted'
                        }`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ clipPath: 'polygon(0 0, 100% 0, 100% 100%)' }}
                    />
                    <span className="absolute top-[3px] right-[3px] z-10 text-white text-[10px] leading-none font-bold">
                        {isQuarantined ? 'Q' : snapshot.review_state === 'approved' ? '✓' : '~'}
                    </span>
                </>
            )}
            <div className="w-[104px] h-[72px] rounded-sm overflow-hidden bg-bg-3000 relative">
                {snapshot.current_artifact?.download_url ? (
                    <>
                        {!imageLoaded && <LemonSkeleton className="absolute inset-0" />}
                        <img
                            src={snapshot.current_artifact.download_url}
                            alt=""
                            width={104}
                            height={72}
                            loading="lazy"
                            decoding="async"
                            className={`w-full h-full object-contain transition-opacity duration-150 ${isQuarantined ? 'grayscale opacity-40' : imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                            onLoad={() => setImageLoaded(true)}
                            onError={() => setImageLoaded(true)}
                        />
                    </>
                ) : (
                    <div className="w-full h-full flex items-center justify-center">
                        <span className="text-[10px] text-muted">No image</span>
                    </div>
                )}
                {isQuarantined && (
                    <span className="absolute inset-0 flex items-center justify-center z-10 text-[10px] font-semibold text-warning-dark bg-warning/20 uppercase tracking-wide">
                        Quarantined
                    </span>
                )}
            </div>
            <div className="flex items-center gap-1 max-w-[108px] w-full">
                {hasDiff ? (
                    <span className="shrink-0 bg-warning-highlight rounded-full px-1.5 py-0.5 text-[10px] font-mono tabular-nums text-warning-dark leading-none">
                        {snapshot.diff_percentage! < 1
                            ? snapshot.diff_percentage!.toFixed(1)
                            : Math.round(snapshot.diff_percentage!)}
                        %
                    </span>
                ) : (
                    <SnapshotStatusIndicator
                        result={snapshot.result || 'unchanged'}
                        reviewState=""
                        classificationReason={snapshot.classification_reason}
                        size="small"
                    />
                )}
                <span className={`text-[11px] truncate ${isSelected ? 'font-medium' : 'text-muted'}`}>{shortName}</span>
            </div>
        </button>
    )
}

function RunInProgressEmptyState({ isProcessing }: { isProcessing: boolean }): JSX.Element {
    const title = isProcessing ? 'Processing diffs' : 'Waiting for snapshots'
    const copy = isProcessing
        ? 'Snapshots are being compared against the baseline. This usually takes under a minute.'
        : 'This run is waiting for the CI job to upload snapshot artifacts. It will appear here once the upload completes.'

    return (
        <PostHogCaptureOnViewed
            name="visual-review-run-in-progress-shown"
            properties={{ is_processing: isProcessing }}
            className="flex flex-col items-center justify-center text-center gap-3 py-12 px-6"
            data-attr="visual-review-run-in-progress"
        >
            <DetectiveHog className="w-32 h-32" />
            <h2 className="m-0">{title}</h2>
            <p className="max-w-md text-tertiary m-0">
                {copy}
                {isProcessing && <Spinner textColored className="ml-2 align-middle" />}
            </p>
        </PostHogCaptureOnViewed>
    )
}

export function VisualReviewRunScene(): JSX.Element {
    const {
        run,
        runLoading,
        snapshots,
        snapshotsLoading,
        selectedSnapshot,
        sortedChangedSnapshots,
        snapshotHistory,
        snapshotHistoryLoading,
        toleratedHashes,
        toleratedHashesLoading,
        quarantinedIdentifiers,
        quarantinedIdentifierSet,
        repoFullName,
        isApproving,
        isApprovingSnapshot,
        isRunInProgress,
        isRunProcessing,
    } = useValues(visualReviewRunSceneLogic)
    const {
        setSelectedSnapshotId,
        approveChanges,
        approveSnapshot,
        markAsTolerated,
        quarantineSnapshot,
        unquarantineSnapshot,
    } = useActions(visualReviewRunSceneLogic)

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

    if (isRunInProgress) {
        return (
            <SceneContent>
                <SceneTitleSection name={run.branch} resourceType={{ type: 'visual_review' }} />
                <RunInProgressEmptyState isProcessing={isRunProcessing} />
            </SceneContent>
        )
    }

    if (run.status === 'failed') {
        return (
            <SceneContent>
                <SceneTitleSection name={run.branch} resourceType={{ type: 'visual_review' }} />
                <LemonBanner type="error">
                    This run failed to process.{run.error_message ? ` ${run.error_message}` : ''} Check the CI logs for
                    details, or rerun the job to try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    // Review summary (from loaded snapshots — paginated but covers actionable ones first)
    // Quarantined snapshots don't need review — exclude from pending count
    const reviewPending = snapshots.filter(
        (s: SnapshotApi) =>
            s.result !== 'unchanged' && s.review_state === 'pending' && !quarantinedIdentifierSet.has(s.identifier)
    ).length
    const reviewApproved = snapshots.filter((s: SnapshotApi) => s.review_state === 'approved').length
    const reviewTolerated = snapshots.filter((s: SnapshotApi) => s.review_state === 'tolerated').length

    // Diff summary (server-side counts)
    const diffChanged = run.summary.changed
    const diffNew = run.summary.new
    const diffRemoved = run.summary.removed
    const diffTolerated = Math.max(0, (run.summary.tolerated_matched ?? 0) - reviewTolerated)

    // If server counts are higher than loaded, show "+" to hint at pagination
    const totalActionable = diffChanged + diffNew + diffRemoved
    const loadedActionable = reviewPending + reviewApproved + reviewTolerated
    const hasMore = totalActionable > loadedActionable

    // Navigation — use changed snapshots when there are changes, otherwise all snapshots
    const navSnapshots = sortedChangedSnapshots.length > 0 ? sortedChangedSnapshots : snapshots
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
                    !run.approved &&
                    !run.is_stale &&
                    (reviewPending > 0 || reviewApproved > 0 || reviewTolerated > 0) ? (
                        <LemonButton type="primary" onClick={approveChanges} loading={isApproving}>
                            {reviewPending > 0 ? `Approve ${reviewPending} pending and commit` : 'Commit to baseline'}
                        </LemonButton>
                    ) : undefined
                }
            />

            {run.is_stale && (
                <LemonBanner type="warning" className="mb-4">
                    This run has been superseded by a newer run.{' '}
                    {run.superseded_by_id && (
                        <Link to={`/visual_review/runs/${run.superseded_by_id}`} className="font-semibold">
                            View latest run
                        </Link>
                    )}
                </LemonBanner>
            )}

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
                                    <span key="new" className="text-success">
                                        {diffNew} added
                                    </span>
                                ),
                                diffRemoved > 0 && (
                                    <span key="rm" className="text-danger">
                                        {diffRemoved} removed
                                    </span>
                                ),
                                diffTolerated > 0 && <span key="tol">{diffTolerated} auto-tolerated</span>,
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
                                    isQuarantined={quarantinedIdentifierSet.has(snapshot.identifier)}
                                    onClick={() => setSelectedSnapshotId(snapshot.id)}
                                />
                            ))}
                        </div>
                    )}

                    {/* Pagination — below thumbnails, right-aligned */}
                    {navSnapshots.length > 1 && (
                        <div className="flex items-center justify-end gap-2 px-3 pb-2">
                            <LemonButton
                                size="xsmall"
                                icon={<IconChevronLeft />}
                                onClick={goToPrevious}
                                disabledReason={!hasPrevious ? 'No previous snapshot' : undefined}
                            >
                                Previous
                            </LemonButton>
                            {currentIndex >= 0 && (
                                <span className="text-xs text-muted">
                                    {currentIndex + 1} of {navSnapshots.length}
                                </span>
                            )}
                            <LemonButton
                                size="xsmall"
                                sideIcon={<IconChevronRight />}
                                onClick={goToNext}
                                disabledReason={!hasNext ? 'No next snapshot' : undefined}
                            >
                                Next
                            </LemonButton>
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
                            isApproving={isApprovingSnapshot}
                            onMarkTolerated={() => markAsTolerated(selectedSnapshot)}
                            quarantineEntry={
                                quarantinedIdentifiers.find(
                                    (q) =>
                                        q.identifier === selectedSnapshot.identifier &&
                                        q.run_type === run.run_type &&
                                        (!q.expires_at || new Date(q.expires_at) > new Date())
                                ) ?? null
                            }
                            onQuarantine={(reason, identifiers, expiresAt) =>
                                quarantineSnapshot(reason, identifiers, expiresAt)
                            }
                            onUnquarantine={() => unquarantineSnapshot(selectedSnapshot)}
                            commitSha={run.commit_sha}
                            prNumber={run.pr_number}
                            repoFullName={repoFullName}
                            runType={run.run_type}
                        />
                    ) : snapshotsLoading ? (
                        <div className="space-y-3 py-4">
                            <LemonSkeleton className="h-6 w-1/4" />
                            <LemonSkeleton className="h-48 w-full" />
                        </div>
                    ) : sortedChangedSnapshots.length > 0 ? (
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
