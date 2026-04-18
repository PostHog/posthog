import { IconChevronLeft, IconChevronRight, IconGithub } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { VisualImageDiffViewer, type VisualDiffResult } from 'lib/components/VisualImageDiffViewer'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { SnapshotApi, SnapshotHistoryEntryApi, ToleratedHashEntryApi } from '../generated/api.schemas'
import { SnapshotStatusIndicator } from './SnapshotStatusIndicator'

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
    snapshotHistory?: SnapshotHistoryEntryApi[]
    snapshotHistoryLoading?: boolean
    toleratedHashes?: ToleratedHashEntryApi[]
    toleratedHashesLoading?: boolean
    onApprove?: () => void
    onMarkTolerated?: () => void
    onPrevious?: () => void
    onNext?: () => void
    hasPrevious?: boolean
    hasNext?: boolean
    currentIndex?: number
    totalCount?: number
    commitSha?: string
    prNumber?: number | null
    repoFullName?: string | null
}

export function SnapshotDiffViewer({
    snapshot,
    snapshotHistory,
    snapshotHistoryLoading,
    toleratedHashes,
    toleratedHashesLoading,
    onApprove,
    onMarkTolerated,
    onPrevious,
    onNext,
    hasPrevious = false,
    hasNext = false,
    currentIndex,
    totalCount,
    commitSha,
    prNumber,
    repoFullName,
}: SnapshotDiffViewerProps): JSX.Element {
    const baselineUrl = snapshot.baseline_artifact?.download_url
    const currentUrl = snapshot.current_artifact?.download_url

    const width = snapshot.current_artifact?.width || snapshot.baseline_artifact?.width
    const height = snapshot.current_artifact?.height || snapshot.baseline_artifact?.height

    const isApproved = snapshot.review_state === 'approved'
    const isTolerated = snapshot.review_state === 'tolerated'
    const hasChanges = snapshot.result === 'changed' || snapshot.result === 'new' || snapshot.result === 'removed'
    const needsAction = hasChanges && !isApproved && !isTolerated

    // Parse identifier for display (e.g., "Feature-Flags-settings--e2e-test--dark--1440x900")
    const parts = snapshot.identifier.split('--')
    const pageName = parts[0]?.replace(/-/g, ' ') || snapshot.identifier
    const variant = parts.slice(1).join(' · ')

    return (
        <div className="flex gap-4">
            {/* Main content area */}
            <div className="flex-1 min-w-0 overflow-hidden">
                {/* Navigation and actions */}
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            size="small"
                            icon={<IconChevronLeft />}
                            onClick={onPrevious}
                            disabled={!hasPrevious}
                        >
                            Previous
                        </LemonButton>
                        {currentIndex !== undefined && totalCount !== undefined && (
                            <span className="text-sm text-muted px-2">
                                {currentIndex + 1} of {totalCount}
                            </span>
                        )}
                        <LemonButton size="small" sideIcon={<IconChevronRight />} onClick={onNext} disabled={!hasNext}>
                            Next
                        </LemonButton>
                    </div>

                    <div className="flex items-center gap-2">
                        <SnapshotStatusIndicator
                            result={snapshot.result || 'unchanged'}
                            reviewState={snapshot.review_state}
                            classificationReason={snapshot.classification_reason}
                        />

                        {needsAction && (
                            <>
                                <LemonButton type="primary" size="small" onClick={onApprove}>
                                    Accept change
                                </LemonButton>
                                {snapshot.result === 'changed' && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Tolerate this difference?',
                                                description:
                                                    'Marks this as rendering noise — future runs with the same hash pass automatically. ' +
                                                    'If this is a bug, fix it instead.',
                                                primaryButton: {
                                                    children: 'Tolerate',
                                                    onClick: onMarkTolerated,
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }}
                                    >
                                        Tolerate
                                    </LemonButton>
                                )}
                            </>
                        )}
                    </div>
                </div>

                {/* Snapshot title */}
                <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-lg font-semibold capitalize">{pageName}</h3>
                    {variant && (
                        <span className="text-sm text-muted">
                            @ {variant}
                            {width && height && ` · ${width}×${height}`}
                        </span>
                    )}
                </div>

                <VisualImageDiffViewer
                    baselineUrl={baselineUrl || null}
                    currentUrl={currentUrl || null}
                    diffUrl={snapshot.diff_artifact?.download_url || null}
                    diffPercentage={snapshot.diff_percentage ?? null}
                    result={(snapshot.result || 'unchanged') as VisualDiffResult}
                />
            </div>

            {/* Right sidebar — flat, no nested cards */}
            <div className="w-52 shrink-0 border-l pl-4 space-y-4">
                {/* Run context */}
                {(commitSha || prNumber) && (
                    <div className="space-y-2">
                        {commitSha && (
                            <div className="flex items-center justify-between text-xs">
                                <span className="text-muted">Commit</span>
                                {repoFullName ? (
                                    <Link
                                        to={`https://github.com/${repoFullName}/commit/${commitSha}`}
                                        target="_blank"
                                        className="flex items-center gap-1 font-mono hover:text-primary"
                                    >
                                        {commitSha.substring(0, 7)}
                                        <IconGithub className="text-xs" />
                                    </Link>
                                ) : (
                                    <span className="font-mono">{commitSha.substring(0, 7)}</span>
                                )}
                            </div>
                        )}
                        {prNumber && (
                            <div className="flex items-center justify-between text-xs">
                                <span className="text-muted">PR</span>
                                {repoFullName ? (
                                    <Link
                                        to={`https://github.com/${repoFullName}/pull/${prNumber}`}
                                        target="_blank"
                                        className="flex items-center gap-1 hover:text-primary"
                                    >
                                        #{prNumber}
                                        <IconGithub className="text-xs" />
                                    </Link>
                                ) : (
                                    <span>#{prNumber}</span>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Snapshot details */}
                <div className="space-y-2">
                    {width && height && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Resolution</span>
                            <span className="font-mono">
                                {width}×{height}
                            </span>
                        </div>
                    )}
                    {snapshot.diff_percentage != null && snapshot.diff_percentage > 0 && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Diff</span>
                            <span className="font-mono">{snapshot.diff_percentage}%</span>
                        </div>
                    )}
                    {snapshot.baseline_artifact?.content_hash && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Baseline</span>
                            <span className="font-mono">{snapshot.baseline_artifact.content_hash.slice(0, 10)}…</span>
                        </div>
                    )}
                    {snapshot.current_artifact?.content_hash && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Current</span>
                            <span className="font-mono">{snapshot.current_artifact.content_hash.slice(0, 10)}…</span>
                        </div>
                    )}
                    {isApproved && snapshot.reviewed_at && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Approved</span>
                            <span className="text-success">{new Date(snapshot.reviewed_at).toLocaleDateString()}</span>
                        </div>
                    )}
                    {isTolerated && snapshot.reviewed_at && (
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-muted">Tolerated</span>
                            <span>{new Date(snapshot.reviewed_at).toLocaleDateString()}</span>
                        </div>
                    )}
                </div>

                {/* Recent activity */}
                <div>
                    <h4 className="text-xs font-semibold text-muted mb-2">History</h4>
                    {snapshotHistoryLoading ? (
                        <div className="space-y-2">
                            <LemonSkeleton className="h-4 w-full" />
                            <LemonSkeleton className="h-4 w-3/4" />
                        </div>
                    ) : snapshotHistory && snapshotHistory.length > 0 ? (
                        <div className="space-y-1.5">
                            {snapshotHistory.map((entry) => (
                                <div key={entry.run_id} className="flex items-center justify-between text-xs">
                                    <span className="font-mono text-muted">{entry.commit_sha.slice(0, 7)}</span>
                                    <LemonTag
                                        type={
                                            entry.result === 'changed'
                                                ? 'warning'
                                                : entry.result === 'new'
                                                  ? 'highlight'
                                                  : entry.result === 'removed'
                                                    ? 'danger'
                                                    : 'muted'
                                        }
                                        size="small"
                                    >
                                        {entry.result}
                                    </LemonTag>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-muted">No history yet</p>
                    )}
                </div>

                {/* Known tolerated hashes */}
                <div>
                    <h4 className="text-xs font-semibold text-muted mb-2">Tolerated hashes</h4>
                    {toleratedHashesLoading ? (
                        <div className="space-y-2">
                            <LemonSkeleton className="h-4 w-full" />
                            <LemonSkeleton className="h-4 w-3/4" />
                        </div>
                    ) : toleratedHashes && toleratedHashes.length > 0 ? (
                        <div className="space-y-1.5">
                            {toleratedHashes.map((entry) => (
                                <div key={entry.id} className="flex items-center justify-between text-xs">
                                    <span className="font-mono text-muted">{entry.alternate_hash.slice(0, 10)}…</span>
                                    <LemonTag type="muted" size="small">
                                        {entry.reason === 'human' ? 'manual' : 'auto'}
                                    </LemonTag>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-muted">None</p>
                    )}
                </div>
            </div>
        </div>
    )
}
