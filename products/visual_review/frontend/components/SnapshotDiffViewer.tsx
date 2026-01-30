import { IconCheck, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import type { SnapshotApi } from '../generated/api.schemas'

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
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

                {/* Side-by-side Before/After */}
                <div className="grid grid-cols-2 gap-4">
                    <div className="flex flex-col">
                        <div className="px-3 py-2 bg-bg-3000 border border-b-0 rounded-t text-sm font-medium">
                            Before
                        </div>
                        <div className="border rounded-b overflow-hidden bg-bg-light flex-1">
                            {baselineUrl ? (
                                <img src={baselineUrl} alt="Before" className="w-full h-auto" />
                            ) : (
                                <div className="p-8 text-center text-muted">No baseline</div>
                            )}
                        </div>
                    </div>
                    <div className="flex flex-col">
                        <div className="px-3 py-2 bg-bg-3000 border border-b-0 rounded-t text-sm font-medium">
                            After
                        </div>
                        <div className="border rounded-b overflow-hidden bg-bg-light flex-1">
                            {currentUrl ? (
                                <img src={currentUrl} alt="After" className="w-full h-auto" />
                            ) : (
                                <div className="p-8 text-center text-muted">No current</div>
                            )}
                        </div>
                    </div>
                </div>

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

                    <div>
                        <h4 className="text-xs font-semibold text-muted uppercase mb-1">Snapshot</h4>
                        <dl className="space-y-1 text-sm">
                            <div className="flex justify-between">
                                <dt className="text-muted">Result</dt>
                                <dd className="font-medium capitalize">{snapshot.result}</dd>
                            </div>
                        </dl>
                    </div>

                    {(snapshot.baseline_artifact?.content_hash || snapshot.current_artifact?.content_hash) && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted uppercase mb-1">Hashes</h4>
                            <dl className="space-y-1 text-sm">
                                {snapshot.baseline_artifact?.content_hash && (
                                    <div>
                                        <dt className="text-muted text-xs">Baseline</dt>
                                        <Tooltip title={snapshot.baseline_artifact.content_hash}>
                                            <dd className="font-mono text-xs truncate">
                                                {snapshot.baseline_artifact.content_hash.slice(0, 12)}...
                                            </dd>
                                        </Tooltip>
                                    </div>
                                )}
                                {snapshot.current_artifact?.content_hash && (
                                    <div>
                                        <dt className="text-muted text-xs">Current</dt>
                                        <Tooltip title={snapshot.current_artifact.content_hash}>
                                            <dd className="font-mono text-xs truncate">
                                                {snapshot.current_artifact.content_hash.slice(0, 12)}...
                                            </dd>
                                        </Tooltip>
                                    </div>
                                )}
                            </dl>
                        </div>
                    )}

                    {snapshot.diff_percentage !== null && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted uppercase mb-1">Diff</h4>
                            <p className="text-sm">
                                <span className="font-semibold">{snapshot.diff_percentage.toFixed(1)}%</span>
                                {snapshot.diff_pixel_count !== null && (
                                    <span className="text-muted">
                                        {' '}
                                        ({snapshot.diff_pixel_count.toLocaleString()} pixels)
                                    </span>
                                )}
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
                </div>
            </div>
        </div>
    )
}
