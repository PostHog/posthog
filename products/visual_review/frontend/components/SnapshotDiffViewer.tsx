import { IconCheck, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { VisualImageDiffViewer, type VisualDiffResult } from 'lib/components/VisualImageDiffViewer'
import { humanFriendlyDetailedTime } from 'lib/utils'

import type { SnapshotApi, SnapshotHistoryEntryApi } from '../generated/api.schemas'

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
    snapshotHistory?: SnapshotHistoryEntryApi[]
    snapshotHistoryLoading?: boolean
    onApprove?: () => void
    onPrevious?: () => void
    onNext?: () => void
    hasPrevious?: boolean
    hasNext?: boolean
    currentIndex?: number
    totalCount?: number
}

export function SnapshotDiffViewer({
    snapshot,
    snapshotHistory,
    snapshotHistoryLoading,
    onApprove,
    onPrevious,
    onNext,
    hasPrevious = false,
    hasNext = false,
    currentIndex,
    totalCount,
}: SnapshotDiffViewerProps): JSX.Element {
    const baselineUrl = snapshot.baseline_artifact?.download_url
    const currentUrl = snapshot.current_artifact?.download_url

    const width = snapshot.current_artifact?.width || snapshot.baseline_artifact?.width
    const height = snapshot.current_artifact?.height || snapshot.baseline_artifact?.height

    const isApproved = snapshot.review_state === 'approved'
    const hasChanges = snapshot.result === 'changed' || snapshot.result === 'new' || snapshot.result === 'removed'

    // Parse identifier for display (e.g., "Feature-Flags-settings--e2e-test--dark--1440x900")
    const parts = snapshot.identifier.split('--')
    const pageName = parts[0]?.replace(/-/g, ' ') || snapshot.identifier
    const variant = parts.slice(1).join(' · ')

    return (
        <div className="flex gap-6">
            {/* Main content area */}
            <div className="flex-1 min-w-0">
                {/* Header */}
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

                {/* Navigation and actions */}
                <div className="flex items-center justify-between mt-4">
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

                    {hasChanges && !isApproved && (
                        <LemonButton type="primary" size="small" icon={<IconCheck />} onClick={onApprove}>
                            Accept change
                        </LemonButton>
                    )}

                    {isApproved && (
                        <span className="flex items-center gap-1 text-sm text-success font-medium">
                            <IconCheck className="w-4 h-4" />
                            Approved
                        </span>
                    )}
                </div>
            </div>

            {/* Right sidebar */}
            <div className="w-56 shrink-0">
                <div className="border rounded-lg p-4 space-y-4">
                    {width && height && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted uppercase mb-1">Environment</h4>
                            <p className="text-sm font-mono">
                                {width}×{height}
                            </p>
                        </div>
                    )}

                    {isApproved && snapshot.reviewed_at && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted uppercase mb-1">Approval</h4>
                            <p className="text-sm text-success">
                                {new Date(snapshot.reviewed_at).toLocaleDateString()}
                            </p>
                        </div>
                    )}

                    {/* Recent activity */}
                    <div>
                        <h4 className="text-xs font-semibold text-muted uppercase mb-2">Recent activity</h4>
                        {snapshotHistoryLoading ? (
                            <div className="space-y-2">
                                <LemonSkeleton className="h-4 w-full" />
                                <LemonSkeleton className="h-4 w-3/4" />
                                <LemonSkeleton className="h-4 w-full" />
                            </div>
                        ) : snapshotHistory && snapshotHistory.length > 0 ? (
                            <div className="space-y-1.5">
                                {snapshotHistory.map((entry) => (
                                    <div key={entry.run_id} className="text-xs flex flex-col gap-0.5">
                                        <div className="flex items-center justify-between">
                                            <span className="font-mono text-muted">{entry.commit_sha.slice(0, 7)}</span>
                                            <span
                                                className={`font-medium capitalize ${
                                                    entry.result === 'changed'
                                                        ? 'text-warning-dark'
                                                        : entry.result === 'new'
                                                          ? 'text-primary-dark'
                                                          : entry.result === 'removed'
                                                            ? 'text-danger'
                                                            : 'text-muted'
                                                }`}
                                            >
                                                {entry.result}
                                            </span>
                                        </div>
                                        <div className="flex items-center justify-between text-muted">
                                            <span className="truncate max-w-[80px]">{entry.branch}</span>
                                            <span>
                                                {humanFriendlyDetailedTime(entry.created_at, 'MMM D', 'h:mm A')}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-xs text-muted">No history yet</p>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
