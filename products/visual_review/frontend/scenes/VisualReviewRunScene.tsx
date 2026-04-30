import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { DetectiveHog } from 'lib/components/hedgehogs'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
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
    thumbnailSrc,
    fallbackSrc,
    onThumbnailFailed,
    onClick,
}: {
    snapshot: SnapshotApi
    isSelected: boolean
    isQuarantined: boolean
    thumbnailSrc: string | null
    fallbackSrc: string | null
    onThumbnailFailed: () => void
    onClick: () => void
}): JSX.Element {
    const parts = snapshot.identifier.split('--')
    const theme = parts[parts.length - 1]
    const isTheme = theme === 'dark' || theme === 'light'
    const shortName = parts.length > 1 ? parts.slice(1, isTheme ? -1 : undefined).join(' · ') : snapshot.identifier

    const isReviewed = snapshot.review_state === 'approved' || snapshot.review_state === 'tolerated'
    const showBadge = isReviewed || isQuarantined
    const hasDiff = snapshot.diff_percentage != null && snapshot.diff_percentage > 0

    const imgSrc = thumbnailSrc ?? fallbackSrc

    return (
        <button
            type="button"
            onClick={onClick}
            data-attr="visual-review-snapshot-thumbnail"
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
                {imgSrc ? (
                    <img
                        src={imgSrc}
                        alt=""
                        width={104}
                        height={72}
                        loading="lazy"
                        decoding="async"
                        className={`w-full h-full object-contain ${isQuarantined ? 'grayscale opacity-40' : ''}`}
                        onError={thumbnailSrc ? onThumbnailFailed : undefined}
                    />
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

const PENDING_STALE_THRESHOLD_MS = 15 * 60 * 1000

function RunInProgressEmptyState({
    isProcessing,
    createdAt,
    ciJobUrl,
}: {
    isProcessing: boolean
    createdAt: string
    ciJobUrl?: string
}): JSX.Element {
    const ageMs = Date.now() - new Date(createdAt).getTime()
    const isStale = !isProcessing && ageMs > PENDING_STALE_THRESHOLD_MS

    const title = isProcessing ? 'Processing diffs' : isStale ? 'Still waiting for snapshots' : 'Waiting for snapshots'
    const copy = isProcessing
        ? 'Snapshots are being compared against the baseline. This usually takes under a minute.'
        : isStale
          ? 'This run has been waiting for over 15 minutes. The CI job may have failed before uploading snapshots.'
          : 'This run is waiting for the CI job to upload snapshot artifacts. It will appear here once the upload completes.'

    return (
        <PostHogCaptureOnViewed
            name="visual-review-run-in-progress-shown"
            properties={{ is_processing: isProcessing, is_stale: isStale }}
            className="flex flex-col items-center justify-center text-center gap-3 py-12 px-6"
            data-attr="visual-review-run-in-progress"
        >
            {isStale ? (
                <LemonBanner type="warning" className="max-w-lg mb-4">
                    The CI job hasn't reported back.{' '}
                    {ciJobUrl ? (
                        <Link to={ciJobUrl} target="_blank" className="font-semibold">
                            Check CI logs
                        </Link>
                    ) : (
                        'Check your CI logs to see if the job failed.'
                    )}
                </LemonBanner>
            ) : null}
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
        snapshots,
        snapshotsLoading,
        selectedSnapshot,
        sortedChangedSnapshots,
        toleratedHashes,
        toleratedHashesLoading,
        quarantinedIdentifiers,
        quarantinedIdentifierSet,
        repoFullName,
        isApproving,
        isApprovingSnapshot,
        isRecomputing,
        isRunInProgress,
        isRunProcessing,
        failedThumbnails,
        thumbnailBasePath,
    } = useValues(visualReviewRunSceneLogic)
    const {
        setSelectedSnapshotId,
        approveChanges,
        approveSnapshot,
        markAsTolerated,
        quarantineSnapshot,
        unquarantineSnapshot,
        recomputeRun,
        markThumbnailFailed,
    } = useActions(visualReviewRunSceneLogic)

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

    useKeyboardHotkeys(
        {
            p: { action: goToPrevious, disabled: !hasPrevious },
            n: { action: goToNext, disabled: !hasNext },
        },
        [currentIndex, navSnapshots.length]
    )

    // Show skeleton only on initial load — once `run` is populated, keep showing it
    // even while a background refetch is in flight (e.g. after approve/tolerate),
    // otherwise the whole scene flashes to skeleton on every mutation.
    if (!run) {
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
                <RunInProgressEmptyState
                    isProcessing={isRunProcessing}
                    createdAt={run.created_at}
                    ciJobUrl={run.metadata?.ci_job_url as string | undefined}
                />
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
    const hasChanges = diffChanged > 0 || diffNew > 0 || diffRemoved > 0

    // Predict whether recompute would flip the gate — uses client-side quarantine set
    // which updates immediately, unlike summary.unresolved which requires a recompute round-trip
    const allChangesResolved =
        run.status === 'completed' &&
        !run.approved &&
        !run.is_stale &&
        hasChanges &&
        snapshots
            .filter((s: SnapshotApi) => s.result !== 'unchanged')
            .every(
                (s: SnapshotApi) =>
                    quarantinedIdentifierSet.has(s.identifier) ||
                    s.review_state === 'tolerated' ||
                    s.review_state === 'approved'
            )

    const hasMore = diffChanged + diffNew + diffRemoved > reviewPending + reviewApproved + reviewTolerated

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
                        <LemonButton
                            type="primary"
                            onClick={approveChanges}
                            loading={isApproving}
                            data-attr="visual-review-commit-baseline"
                        >
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

            {allChangesResolved && (
                <LemonBanner
                    type="info"
                    className="mb-4"
                    action={{
                        children: 'Re-trigger CI',
                        loading: isRecomputing,
                        onClick: recomputeRun,
                        'data-attr': 'visual-review-recompute-run',
                    }}
                >
                    All changes are resolved — re-trigger to update the commit status and pass the gate.
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
                            {navSnapshots.map((snapshot: SnapshotApi) => {
                                const hasThumbnail = thumbnailBasePath && !failedThumbnails.has(snapshot.identifier)
                                return (
                                    <SnapshotThumbnail
                                        key={snapshot.id}
                                        snapshot={snapshot}
                                        isSelected={selectedSnapshot?.id === snapshot.id}
                                        isQuarantined={quarantinedIdentifierSet.has(snapshot.identifier)}
                                        thumbnailSrc={
                                            hasThumbnail
                                                ? `${thumbnailBasePath}/${encodeURIComponent(snapshot.identifier)}/`
                                                : null
                                        }
                                        fallbackSrc={snapshot.current_artifact?.download_url ?? null}
                                        onThumbnailFailed={() => markThumbnailFailed(snapshot.identifier)}
                                        onClick={() => setSelectedSnapshotId(snapshot.id)}
                                    />
                                )
                            })}
                        </div>
                    )}

                    {/* Pagination — below thumbnails, right-aligned */}
                    {navSnapshots.length > 1 && (
                        <div className="flex items-center justify-end gap-2 px-3 pb-2">
                            <LemonButton
                                size="xsmall"
                                icon={<IconChevronLeft />}
                                sideIcon={<KeyboardShortcut p />}
                                onClick={goToPrevious}
                                disabledReason={!hasPrevious ? 'No previous snapshot' : undefined}
                                data-attr="visual-review-snapshot-previous"
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
                                icon={<KeyboardShortcut n />}
                                sideIcon={<IconChevronRight />}
                                onClick={goToNext}
                                disabledReason={!hasNext ? 'No next snapshot' : undefined}
                                data-attr="visual-review-snapshot-next"
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
                            repoId={run.repo_id}
                            repoFullName={repoFullName}
                            runType={run.run_type}
                            githubRunId={(run.metadata?.github_run_id as string) || null}
                            isRecomputing={isRecomputing}
                            onRecompute={
                                run.status === 'completed' && !run.approved && !run.is_stale ? recomputeRun : undefined
                            }
                            recomputeDisabledReason={
                                !allChangesResolved ? 'Re-trigger would not change the outcome' : undefined
                            }
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
