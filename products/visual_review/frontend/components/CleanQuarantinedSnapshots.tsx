import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import type { SnapshotApi } from '../generated/api.schemas'

interface CleanQuarantinedSnapshotsProps {
    snapshots: SnapshotApi[]
    loading: boolean
    loadFailed: boolean
    selectedSnapshotId: string | null
    onSelect: (snapshotId: string) => void
}

/** Quarantined stories this run rendered exactly as their baseline, which the changes-only strip leaves out. */
export function CleanQuarantinedSnapshots({
    snapshots,
    loading,
    loadFailed,
    selectedSnapshotId,
    onSelect,
}: CleanQuarantinedSnapshotsProps): JSX.Element | null {
    if (loading) {
        return (
            <div className="px-3 pb-3">
                <LemonSkeleton className="h-4 w-1/3" />
            </div>
        )
    }
    if (loadFailed) {
        return (
            <div className="px-3 pb-3 text-xs text-muted" data-attr="visual-review-clean-quarantined-error">
                Couldn't load the quarantined stories of this run. Reload the page to lift a quarantine when this pull
                request merges.
            </div>
        )
    }
    if (snapshots.length === 0) {
        return null
    }
    return (
        <div className="px-3 pb-3" data-attr="visual-review-clean-quarantined">
            <div className="text-xs font-semibold">Quarantined stories that rendered clean</div>
            <div className="text-xs text-muted mb-1.5">
                Select one to lift its quarantine when this pull request merges.
            </div>
            <div className="flex flex-wrap gap-1">
                {snapshots.map((snapshot) => (
                    <LemonButton
                        key={snapshot.id}
                        type="secondary"
                        size="xsmall"
                        active={snapshot.id === selectedSnapshotId}
                        onClick={() => onSelect(snapshot.id)}
                        data-attr="visual-review-clean-quarantined-select"
                    >
                        {snapshot.identifier}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
