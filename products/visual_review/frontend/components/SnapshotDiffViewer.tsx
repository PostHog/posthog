import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { VisualImageDiffViewer, type VisualDiffResult } from 'lib/components/VisualImageDiffViewer'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import type { QuarantinedIdentifierEntryApi, SnapshotApi, ToleratedHashEntryApi } from '../generated/api.schemas'
import { visualReviewPreferencesLogic } from '../scenes/visualReviewPreferencesLogic'
import { DiffPercentage } from './DiffPercentage'
import { SnapshotStatusIndicator } from './SnapshotStatusIndicator'

function DiffMinimap({ url, onClick }: { url: string; onClick?: () => void }): JSX.Element {
    const [loaded, setLoaded] = useState(false)
    return (
        <div>
            <h4 className="text-xs font-semibold text-muted mb-2">Diff map</h4>
            <button
                type="button"
                className="relative rounded border border-border overflow-hidden bg-bg-3000 w-full cursor-pointer hover:border-primary transition-colors"
                onClick={onClick}
                data-attr="visual-review-diff-minimap"
            >
                {!loaded && <LemonSkeleton className="absolute inset-0" />}
                <img
                    src={url}
                    alt="Diff heatmap"
                    className={`w-full object-contain transition-opacity duration-150 ${loaded ? 'opacity-100' : 'opacity-0'}`}
                    onLoad={() => setLoaded(true)}
                    onError={() => setLoaded(true)}
                />
            </button>
        </div>
    )
}

function getThemeSibling(identifier: string): string | null {
    const parts = identifier.split('--')
    const themeIndex = [...parts].reverse().findIndex((part) => part === 'dark' || part === 'light')
    if (themeIndex === -1) {
        return null
    }
    const actualIndex = parts.length - 1 - themeIndex
    const siblingParts = [...parts]
    siblingParts[actualIndex] = siblingParts[actualIndex] === 'dark' ? 'light' : 'dark'
    return siblingParts.join('--')
}

const SUGGESTED_REASONS = [
    'Non-deterministic rendering (animations, timestamps)',
    'Font hinting varies across environments',
    'Async content loading race condition',
    'Known flaky — fix in progress',
]

const DEFAULT_EXPIRY_DAYS = 30

function QuarantineAction({
    identifier,
    onQuarantine,
}: {
    identifier: string
    onQuarantine: (reason: string, identifiers: string[], expiresAt: string | null) => void
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [reason, setReason] = useState('')
    const [includeSibling, setIncludeSibling] = useState(true)
    const [expiresAt, setExpiresAt] = useState<dayjs.Dayjs | null>(dayjs().add(DEFAULT_EXPIRY_DAYS, 'day'))

    const sibling = getThemeSibling(identifier)

    const handleSubmit = (): void => {
        const identifiers = [identifier]
        if (sibling && includeSibling) {
            identifiers.push(sibling)
        }
        onQuarantine(reason, identifiers, expiresAt ? expiresAt.toISOString() : null)
        setIsOpen(false)
        setReason('')
        setExpiresAt(dayjs().add(DEFAULT_EXPIRY_DAYS, 'day'))
    }

    return (
        <div>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setIsOpen(true)}
                data-attr="visual-review-quarantine-open"
            >
                Quarantine this identifier
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Quarantine snapshot"
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={() => setIsOpen(false)}
                            data-attr="visual-review-quarantine-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!reason.trim() ? 'Reason is required' : undefined}
                            onClick={handleSubmit}
                            data-attr="visual-review-quarantine-confirm"
                        >
                            Quarantine
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        Quarantined identifiers appear as quarantined immediately and are excluded from gating when
                        future runs finalize — including pending runs on other branches. Snapshots are still captured
                        and diffed, just not gated on.
                    </p>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Identifier</label>
                        <div className="font-mono text-xs text-muted bg-bg-3000 rounded px-2 py-1.5">{identifier}</div>
                        {sibling && (
                            <LemonCheckbox
                                className="mt-1.5"
                                label={
                                    <span className="text-xs">
                                        Also quarantine <span className="font-mono">{sibling}</span>
                                    </span>
                                }
                                checked={includeSibling}
                                onChange={setIncludeSibling}
                            />
                        )}
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Reason</label>
                        <LemonInput
                            placeholder="Why is this snapshot quarantined?"
                            value={reason}
                            onChange={setReason}
                            autoFocus
                        />
                        <div className="flex flex-wrap gap-1 mt-1.5">
                            {SUGGESTED_REASONS.map((suggestion) => (
                                <button
                                    key={suggestion}
                                    type="button"
                                    className="text-[11px] text-muted hover:text-default bg-bg-3000 hover:bg-border rounded px-1.5 py-0.5 transition-colors"
                                    onClick={() => setReason(suggestion)}
                                >
                                    {suggestion}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-1 block">Expires</label>
                        <LemonCalendarSelectInput
                            value={expiresAt}
                            onChange={setExpiresAt}
                            placeholder="No expiry"
                            clearable
                        />
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
    toleratedHashes?: ToleratedHashEntryApi[]
    toleratedHashesLoading?: boolean
    onApprove?: () => void
    isApproving?: boolean
    onMarkTolerated?: () => void
    quarantineEntry?: QuarantinedIdentifierEntryApi | null
    onQuarantine?: (reason: string, identifiers: string[], expiresAt: string | null) => void
    onUnquarantine?: () => void
    commitSha?: string
    prNumber?: number | null
    repoId?: string | null
    repoFullName?: string | null
    runType?: string
    githubRunId?: string | null
    isRecomputing?: boolean
    onRecompute?: () => void
    recomputeDisabledReason?: string
}

export function SnapshotDiffViewer({
    snapshot,
    toleratedHashes,
    toleratedHashesLoading,
    onApprove,
    isApproving,
    onMarkTolerated,
    quarantineEntry,
    onQuarantine,
    onUnquarantine,
    commitSha,
    prNumber,
    repoId,
    repoFullName,
    runType,
    githubRunId,
    isRecomputing,
    onRecompute,
    recomputeDisabledReason,
}: SnapshotDiffViewerProps): JSX.Element {
    const { comparisonMode } = useValues(visualReviewPreferencesLogic)
    const { setComparisonMode } = useActions(visualReviewPreferencesLogic)
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
                                data-attr="visual-review-snapshot-reject"
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
                                    data-attr="visual-review-snapshot-tolerate"
                                >
                                    Tolerate
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={onApprove}
                                loading={isApproving}
                                data-attr="visual-review-snapshot-accept"
                            >
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
                        <div className="bg-warning-highlight border border-warning rounded px-3 py-2 mb-4 text-sm text-muted-alt flex items-center gap-1.5">
                            <span>
                                Quarantined — {quarantineEntry.reason}
                                {quarantineEntry.expires_at &&
                                    ` · until ${new Date(quarantineEntry.expires_at).toLocaleDateString()}`}
                            </span>
                            {quarantineEntry.created_by && (
                                <>
                                    <span>·</span>
                                    <ProfilePicture user={quarantineEntry.created_by} size="xs" showName />
                                </>
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
                        imageHeight={height ?? undefined}
                        mode={comparisonMode}
                        onModeChange={setComparisonMode}
                        className="min-h-[200px]"
                    />
                </div>

                {/* Right sidebar */}
                <div className="w-52 shrink-0 border-l pl-4 space-y-4">
                    {/* === Diff minimap === */}
                    {snapshot.diff_artifact?.download_url && (
                        <DiffMinimap
                            url={snapshot.diff_artifact.download_url}
                            onClick={() => setComparisonMode('diff')}
                        />
                    )}

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
                                        <div className="flex items-center gap-1">
                                            {snapshot.reviewed_by && (
                                                <ProfilePicture user={snapshot.reviewed_by} size="xs" />
                                            )}
                                            <span className="text-success">
                                                {new Date(snapshot.reviewed_at).toLocaleDateString()}
                                            </span>
                                        </div>
                                    </div>
                                )}
                                {isTolerated && snapshot.reviewed_at && (
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-muted">Tolerated</span>
                                        <div className="flex items-center gap-1">
                                            {snapshot.reviewed_by && (
                                                <ProfilePicture user={snapshot.reviewed_by} size="xs" />
                                            )}
                                            <span>{new Date(snapshot.reviewed_at).toLocaleDateString()}</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* === CI section === */}
                    {(githubRunId || onRecompute) && (
                        <div>
                            <h4 className="text-xs font-semibold text-muted mb-2">CI</h4>
                            <div className="space-y-2">
                                {githubRunId && (
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="text-muted">Run</span>
                                        {repoFullName ? (
                                            <Link
                                                to={`https://github.com/${repoFullName}/actions/runs/${githubRunId}`}
                                                target="_blank"
                                                className="flex items-center gap-1 hover:text-primary"
                                            >
                                                {githubRunId}
                                                <IconGithub className="text-xs" />
                                            </Link>
                                        ) : (
                                            <span>{githubRunId}</span>
                                        )}
                                    </div>
                                )}
                                {onRecompute && (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        loading={isRecomputing}
                                        disabledReason={recomputeDisabledReason}
                                        data-attr="visual-review-snapshot-recompute"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Re-trigger CI job?',
                                                description: githubRunId
                                                    ? `Re-evaluate quarantine rules, update snapshot counts and commit status, and re-trigger CI run ${githubRunId} so the gate reflects the current state.`
                                                    : 'Re-evaluate quarantine rules and update snapshot counts and commit status. The CI job cannot be re-triggered automatically — upgrade the CLI to enable this.',
                                                primaryButton: {
                                                    children: githubRunId ? `Re-trigger ${githubRunId}` : 'Recompute',
                                                    onClick: onRecompute,
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }}
                                    >
                                        Re-trigger
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    )}

                    {/* === Identifier section === */}
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-2">Identifier</h4>
                        <div className="space-y-2">
                            <div className="text-xs">
                                {repoId && runType ? (
                                    <Link
                                        to={urls.visualReviewSnapshotHistory(repoId, runType, snapshot.identifier)}
                                        className="font-mono text-default break-all"
                                        title="View history"
                                    >
                                        {snapshot.identifier}
                                    </Link>
                                ) : (
                                    <span className="font-mono break-all">{snapshot.identifier}</span>
                                )}
                            </div>
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
                                    <DiffPercentage value={snapshot.diff_percentage} suffix="" />
                                </div>
                            )}
                            {snapshot.baseline_artifact?.content_hash && (
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-muted">Before</span>
                                    {repoId && runType ? (
                                        <Link
                                            to={urls.visualReviewSnapshotHistory(repoId, runType, snapshot.identifier)}
                                            className="font-mono"
                                            title="View history"
                                        >
                                            {snapshot.baseline_artifact.content_hash.slice(0, 10)}…
                                        </Link>
                                    ) : (
                                        <span className="font-mono">
                                            {snapshot.baseline_artifact.content_hash.slice(0, 10)}…
                                        </span>
                                    )}
                                </div>
                            )}
                            {snapshot.current_artifact?.content_hash && (
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-muted">After</span>
                                    {repoId && runType ? (
                                        <Link
                                            to={urls.visualReviewSnapshotHistory(repoId, runType, snapshot.identifier)}
                                            className="font-mono"
                                            title="View history"
                                        >
                                            {snapshot.current_artifact.content_hash.slice(0, 10)}…
                                        </Link>
                                    ) : (
                                        <span className="font-mono">
                                            {snapshot.current_artifact.content_hash.slice(0, 10)}…
                                        </span>
                                    )}
                                </div>
                            )}
                            {repoId && runType && (
                                <div className="pt-1">
                                    <Link
                                        to={urls.visualReviewSnapshotHistory(repoId, runType, snapshot.identifier)}
                                        className="text-xs"
                                    >
                                        View history →
                                    </Link>
                                </div>
                            )}
                        </div>
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
                    {isQuarantined && onUnquarantine && (
                        <div>
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                data-attr="visual-review-unquarantine"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Unquarantine this identifier?',
                                        description:
                                            'This identifier will be gated on again in future runs. ' +
                                            'Branches that haven\u2019t merged the fix may get blocked.',
                                        primaryButton: {
                                            children: 'Unquarantine',
                                            status: 'danger',
                                            onClick: onUnquarantine,
                                        },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }}
                            >
                                Unquarantine
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
