import { LemonButton } from '@posthog/lemon-ui'

import type { SnapshotApi } from '../generated/api.schemas'

interface CleanQuarantinedSnapshotsProps {
    snapshots: SnapshotApi[]
    selectedSnapshotId: string | null
    onSelect: (snapshotId: string) => void
}

/** Quarantined stories this run rendered exactly as their baseline, which the changes-only strip leaves out. */
export function CleanQuarantinedSnapshots({
    snapshots,
    selectedSnapshotId,
    onSelect,
}: CleanQuarantinedSnapshotsProps): JSX.Element | null {
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
