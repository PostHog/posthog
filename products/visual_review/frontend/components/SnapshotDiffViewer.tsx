import { useState } from 'react'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { VisualImageDiffViewer, type VisualDiffResult } from 'lib/components/VisualImageDiffViewer'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type {
    QuarantinedIdentifierEntryApi,
    SnapshotApi,
    SnapshotHistoryEntryApi,
    ToleratedHashEntryApi,
} from '../generated/api.schemas'
import { SnapshotStatusIndicator } from './SnapshotStatusIndicator'

function getThemeSibling(identifier: string): string | null {
    const parts = identifier.split('--')
    const theme = parts[parts.length - 1]
    if (theme === 'dark') {
        return [...parts.slice(0, -1), 'light'].join('--')
    }
    if (theme === 'light') {
        return [...parts.slice(0, -1), 'dark'].join('--')
    }
    return null
}

function QuarantineAction({
    identifier,
    onQuarantine,
}: {
    identifier: string
    onQuarantine: (reason: string, identifiers: string[]) => void
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [reason, setReason] = useState('')
    const [includeSibling, setIncludeSibling] = useState(true)

    const sibling = getThemeSibling(identifier)

    const handleSubmit = (): void => {
        const identifiers = [identifier]
        if (sibling && includeSibling) {
            identifiers.push(sibling)
        }
        onQuarantine(reason, identifiers)
        setIsOpen(false)
        setReason('')
    }

    return (
        <div>
            <LemonButton type="secondary" size="small" fullWidth onClick={() => setIsOpen(true)}>
                Quarantine this identifier
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Quarantine snapshot"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!reason.trim() ? 'Reason is required' : undefined}
                            onClick={handleSubmit}
                        >
                            Quarantine
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        This will stop blocking PRs immediately — including pending runs on other branches. Snapshots
                        are still captured and diffed, just not gated on. You can reverse this at any time.
                    </p>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Reason</label>
                        <LemonInput
                            placeholder="e.g. Flaky due to animation timing"
                            value={reason}
                            onChange={setReason}
                            autoFocus
                        />
                    </div>

                    <div className="text-xs text-muted space-y-1">
                        <div className="font-mono">{identifier}</div>
                        {sibling && (
                            <LemonCheckbox
                                label={<span className="font-mono text-xs">{sibling}</span>}
                                checked={includeSibling}
                                onChange={setIncludeSibling}
                            />
                        )}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
    snapshotHistory?: SnapshotHistoryEntryApi[]
    snapshotHistoryLoading?: boolean
    toleratedHashes?: ToleratedHashEntryApi[]
    toleratedHashesLoading?: boolean
    onApprove?: () => void
    onMarkTolerated?: () => void
    quarantineEntry?: QuarantinedIdentifierEntryApi | null
    onQuarantine?: (reason: string, identifiers: string[]) => void
    onUnquarantine?: () => void
    commitSha?: string
    prNumber?: number | null
    repoFullName?: string | null
    runType?: string
}

export function SnapshotDiffViewer({
    snapshot,
    snapshotHistory,
    snapshotHistoryLoading,
    toleratedHashes,
    toleratedHashesLoading,
    onApprove,
    onMarkTolerated,
    quarantineEntry,
    onQuarantine,
    onUnquarantine,
    commitSha,
    prNumber,
    repoFullName,
    runType,
}: SnapshotDiffViewerProps): JSX.Element {
    const baselineUrl = snapshot.baseline_artifact?.download_url
    const currentUrl = snapshot.current_artifact?.download_url

    const width = snapshot.current_artifact?.width || snapshot.baseline_artifact?.width
    const height = snapshot.current_artifact?.height || snapshot.baseline_artifact?.height

    const isApproved = snapshot.review_state === 'approved'
    const isTolerated = snapshot.review_state === 'tolerated'
    const isQuarantined = !!quarantineEntry
    const hasChanges = snapshot.result === 'changed' || snapshot.result === 'new' || snapshot.result === 'removed'
    const needsAction = hasChanges && !isApproved && !isTolerated && !isQuarantined

    // Parse identifier for display (e.g., "Feature-Flags-settings--e2e-test--dark--1440x900")
    const parts = snapshot.identifier.split('--')
    const pageName = parts[0]?.replace(/-/g, ' ') || snapshot.identifier
    const variant = parts.slice(1).join(' · ')

    return (
        <div>
            {/* Title + status + actions — full width above content+sidebar */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-baseline gap-2">
                    <h3 className="text-lg font-semibold capitalize">{pageName}</h3>
                    {variant && (
                        <span className="text-sm text-muted">
                            @ {variant}
                            {width && height && ` · ${width}×${height}`}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    <SnapshotStatusIndicator
                        result={snapshot.result || 'unchanged'}
                        reviewState={snapshot.review_state}
                        classificationReason={snapshot.classification_reason}
                    />

                    {needsAction && (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                disabledReason="Leaving a snapshot unreviewed already blocks the PR. To fix it, update your code and rerun CI."
                            >
                                Reject
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
                            <LemonButton type="primary" size="small" onClick={onApprove}>
                                Accept change
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>

            {/* Content + sidebar */}
            <div className="flex gap-4">
                <div className="flex-1 min-w-0 overflow-hidden">
                    {isQuarantined && quarantineEntry && (
                        <div className="flex items-center justify-between bg-warning-highlight border border-warning rounded px-3 py-2 mb-4 text-sm">
                            <span className="text-muted-alt">
                                Quarantined — {quarantineEntry.reason}
                                {quarantineEntry.expires_at &&
                                    ` · until ${new Date(quarantineEntry.expires_at).toLocaleDateString()}`}
                            </span>
                            {onUnquarantine && (
                                <LemonButton size="xsmall" type="secondary" onClick={onUnquarantine}>
                                    Unquarantine
                                </LemonButton>
                            )}
                        </div>
                    )}

                    <VisualImageDiffViewer
                        key={snapshot.id}
                        baselineUrl={baselineUrl || null}
                        currentUrl={currentUrl || null}
                        diffUrl={snapshot.diff_artifact?.download_url || null}
                        diffPercentage={snapshot.diff_percentage ?? null}
                        result={(snapshot.result || 'unchanged') as VisualDiffResult}
                        imageWidth={width ?? undefined}
                        className="min-h-[200px]"
                    />
                </div>

                {/* Right sidebar */}
                <div className="w-52 shrink-0 border-l pl-4 space-y-4">
                    {/* === Run section === */}
                    {(runType || commitSha || prNumber) && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted mb-2">Run</h4>
                            <div className="space-y-2">
                                {runType && (
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-muted">Type</span>
                                        <LemonTag type="muted" size="small" className="uppercase">
                                            {runType}
                                        </LemonTag>
                                    </div>
                                )}
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
                                {isApproved && snapshot.reviewed_at && (
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-muted">Approved</span>
                                        <span className="text-success">
                                            {new Date(snapshot.reviewed_at).toLocaleDateString()}
                                        </span>
                                    </div>
                                )}
                                {isTolerated && snapshot.reviewed_at && (
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-muted">Tolerated</span>
                                        <span>{new Date(snapshot.reviewed_at).toLocaleDateString()}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* === Identifier section === */}
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-2">Identifier</h4>
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
                                    <span className="font-mono">{Number(snapshot.diff_percentage.toFixed(2))}%</span>
                                </div>
                            )}
                            {snapshot.baseline_artifact?.content_hash && (
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-muted">Baseline</span>
                                    <span className="font-mono">
                                        {snapshot.baseline_artifact.content_hash.slice(0, 10)}…
                                    </span>
                                </div>
                            )}
                            {snapshot.current_artifact?.content_hash && (
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-muted">Current</span>
                                    <span className="font-mono">
                                        {snapshot.current_artifact.content_hash.slice(0, 10)}…
                                    </span>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* History */}
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
                                        <SnapshotStatusIndicator result={entry.result} reviewState="" size="medium" />
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-xs text-muted">No history yet</p>
                        )}
                    </div>

                    {/* Tolerated hashes */}
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
                                        <span className="font-mono text-muted">
                                            {entry.alternate_hash.slice(0, 10)}…
                                        </span>
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

                    {/* Quarantine */}
                    {hasChanges && !isQuarantined && onQuarantine && (
                        <QuarantineAction identifier={snapshot.identifier} onQuarantine={onQuarantine} />
                    )}
                </div>
            </div>
        </div>
    )
}
