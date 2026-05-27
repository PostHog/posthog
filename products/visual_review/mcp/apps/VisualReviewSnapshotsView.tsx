import { type ReactElement, useCallback, useMemo, useState } from 'react'

import { Badge, Button, Card, CardContent } from '@posthog/quill'

import type { ArtifactApi, PaginatedSnapshotListApi, SnapshotApi } from '../../frontend/generated/api.schemas'

export type VisualReviewArtifact = ArtifactApi
export type VisualReviewSnapshot = SnapshotApi
export type VisualReviewSnapshotsData = PaginatedSnapshotListApi & { _posthogUrl?: string }

export type SnapshotAction = 'approve' | 'tolerate'

export interface ActionState {
    loadingAs: SnapshotAction | null
    error: string | null
    succeededAs: SnapshotAction | null
}

export interface VisualReviewSnapshotsViewProps {
    data: VisualReviewSnapshotsData
    onAction?: (snapshot: VisualReviewSnapshot, action: SnapshotAction) => Promise<void>
    actionStates?: Record<string, ActionState>
}

const resultVariant: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    unchanged: 'success',
    changed: 'destructive',
    new: 'warning',
    removed: 'default',
}

function resultLabel(result: string): string {
    return result.charAt(0).toUpperCase() + result.slice(1)
}

function formatDiffPct(pct: number | null | undefined): string {
    if (pct == null) {
        return '—'
    }
    return `${pct.toFixed(2)}%`
}

function isApproved(snapshot: VisualReviewSnapshot, state: ActionState | undefined): boolean {
    return snapshot.review_state === 'approved' || state?.succeededAs === 'approve'
}

function isTolerated(state: ActionState | undefined): boolean {
    return state?.succeededAs === 'tolerate'
}

function ArtifactImage({
    label,
    artifact,
}: {
    label: string
    artifact: VisualReviewArtifact | null | undefined
}): ReactElement {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
            <div className="border rounded bg-secondary/30 flex items-center justify-center min-h-[120px] overflow-hidden">
                {artifact?.download_url ? (
                    // eslint-disable-next-line react/forbid-elements
                    <img
                        src={artifact.download_url}
                        alt={`${label} image`}
                        loading="lazy"
                        className="max-w-full max-h-[480px] object-contain"
                    />
                ) : (
                    <span className="text-xs text-muted-foreground p-4">No image</span>
                )}
            </div>
            {artifact && (
                <span className="text-xs text-muted-foreground font-mono truncate">
                    {artifact.content_hash.slice(0, 12)}
                    {artifact.width && artifact.height ? ` · ${artifact.width}×${artifact.height}` : ''}
                </span>
            )}
        </div>
    )
}

function SnapshotRow({
    snapshot,
    onClick,
    isSelected,
    actionState,
}: {
    snapshot: VisualReviewSnapshot
    onClick: () => void
    isSelected: boolean
    actionState: ActionState | undefined
}): ReactElement {
    const variant = resultVariant[snapshot.result] ?? 'default'
    return (
        <button
            type="button"
            onClick={onClick}
            className={
                'flex items-center justify-between gap-2 w-full text-left px-3 py-2 rounded border transition-colors ' +
                (isSelected ? 'bg-secondary border-primary' : 'hover:bg-secondary/50 border-transparent')
            }
        >
            <div className="flex items-center gap-2 min-w-0 flex-1">
                <Badge variant={variant}>{resultLabel(snapshot.result)}</Badge>
                <span className="text-sm truncate">{snapshot.identifier}</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground shrink-0">
                {isApproved(snapshot, actionState) && <Badge variant="success">Approved</Badge>}
                {isTolerated(actionState) && <Badge variant="default">Tolerated</Badge>}
                {snapshot.result === 'changed' && <span>{formatDiffPct(snapshot.diff_percentage)}</span>}
            </div>
        </button>
    )
}

// Bound the rendered list so a broken run with thousands of snapshots
// doesn't melt the host. Snapshots are sorted so the actionable ones
// (changed > new > removed > unchanged) come first.
const MAX_VISIBLE_SNAPSHOTS = 100

const resultOrder: Record<string, number> = { changed: 0, new: 1, removed: 2, unchanged: 3 }

function sortForReview(snapshots: VisualReviewSnapshot[]): VisualReviewSnapshot[] {
    return [...snapshots].sort((a, b) => {
        const ra = resultOrder[a.result] ?? 99
        const rb = resultOrder[b.result] ?? 99
        if (ra !== rb) {
            return ra - rb
        }
        return a.identifier.localeCompare(b.identifier)
    })
}

export function VisualReviewSnapshotsView({
    data,
    onAction,
    actionStates,
}: VisualReviewSnapshotsViewProps): ReactElement {
    const sortedSnapshots = useMemo(() => sortForReview(data.results), [data.results])
    const totalSnapshots = data.count ?? data.results.length
    const snapshots = useMemo(() => sortedSnapshots.slice(0, MAX_VISIBLE_SNAPSHOTS), [sortedSnapshots])
    const truncated = sortedSnapshots.length > MAX_VISIBLE_SNAPSHOTS || totalSnapshots > snapshots.length
    const initialId = useMemo(() => {
        const first = snapshots.find((s) => s.result === 'changed') ?? snapshots[0]
        return first?.id
    }, [snapshots])

    const [selectedId, setSelectedId] = useState<string | undefined>(initialId)
    const selected = snapshots.find((s) => s.id === selectedId) ?? snapshots[0]

    const handleAction = useCallback(
        (action: SnapshotAction) => {
            if (!selected || !onAction) {
                return
            }
            void onAction(selected, action)
        },
        [selected, onAction]
    )

    if (snapshots.length === 0) {
        return (
            <div className="p-4">
                <span className="text-sm text-muted-foreground">No snapshots in this run.</span>
            </div>
        )
    }

    const selectedState = selected ? actionStates?.[selected.id] : undefined
    const isLoading = selectedState?.loadingAs != null
    const approveDisabled =
        !onAction ||
        isLoading ||
        isApproved(selected!, selectedState) ||
        selected!.result === 'unchanged' ||
        selected!.result === 'removed'
    const tolerateDisabled = !onAction || isLoading || selected!.result !== 'changed' || isTolerated(selectedState)

    return (
        <div className="flex flex-col gap-3 p-4">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm text-muted-foreground">
                    {truncated
                        ? `Showing ${snapshots.length} of ${totalSnapshots} snapshots (most actionable first)`
                        : `${snapshots.length} snapshot${snapshots.length === 1 ? '' : 's'}`}
                </span>
                {truncated && (
                    <span className="text-xs text-muted-foreground">
                        Ask the agent to filter (e.g. only `result=changed`) to drill in further.
                    </span>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-3">
                <div className="flex flex-col gap-1 max-h-[600px] overflow-y-auto pr-1">
                    {snapshots.map((snapshot) => (
                        <SnapshotRow
                            key={snapshot.id}
                            snapshot={snapshot}
                            isSelected={snapshot.id === selected!.id}
                            onClick={() => setSelectedId(snapshot.id)}
                            actionState={actionStates?.[snapshot.id]}
                        />
                    ))}
                </div>

                {selected && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                <div className="flex items-center justify-between gap-2 flex-wrap">
                                    <div className="flex flex-col gap-1 min-w-0">
                                        <span className="text-sm font-semibold break-all">{selected.identifier}</span>
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <Badge variant={resultVariant[selected.result] ?? 'default'}>
                                                {resultLabel(selected.result)}
                                            </Badge>
                                            {selected.classification_reason && (
                                                <Badge variant="default">{selected.classification_reason}</Badge>
                                            )}
                                            {selected.change_kind && (
                                                <Badge variant="default">{selected.change_kind}</Badge>
                                            )}
                                            {selected.size_mismatch && <Badge variant="warning">Size mismatch</Badge>}
                                            <span className="text-xs text-muted-foreground">
                                                Diff {formatDiffPct(selected.diff_percentage)}
                                                {selected.diff_pixel_count != null
                                                    ? ` · ${selected.diff_pixel_count.toLocaleString()} px`
                                                    : ''}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <Button
                                            variant="default"
                                            size="sm"
                                            disabled={approveDisabled}
                                            onClick={() => handleAction('approve')}
                                        >
                                            {selectedState?.loadingAs === 'approve' ? 'Working…' : 'Approve'}
                                        </Button>
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            disabled={tolerateDisabled}
                                            onClick={() => handleAction('tolerate')}
                                        >
                                            {selectedState?.loadingAs === 'tolerate' ? 'Working…' : 'Tolerate'}
                                        </Button>
                                    </div>
                                </div>

                                {selectedState?.error && (
                                    <span className="text-xs text-destructive-foreground">{selectedState.error}</span>
                                )}
                                {selectedState?.succeededAs && (
                                    <span className="text-xs text-muted-foreground">
                                        {selectedState.succeededAs === 'approve'
                                            ? 'Approved — baseline updated.'
                                            : 'Tolerated — future runs ignore this variant.'}
                                    </span>
                                )}

                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                    <ArtifactImage label="Baseline" artifact={selected.baseline_artifact} />
                                    <ArtifactImage label="Current" artifact={selected.current_artifact} />
                                    <ArtifactImage label="Diff" artifact={selected.diff_artifact} />
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
