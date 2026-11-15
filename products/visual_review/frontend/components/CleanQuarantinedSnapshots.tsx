import { LemonSkeleton } from '@posthog/lemon-ui'

import type { CleanQuarantinedGroups } from '../lib/liftOnMerge'
import { CleanQuarantinedStoryList } from './CleanQuarantinedStoryList'

interface CleanQuarantinedSnapshotsProps {
    groups: CleanQuarantinedGroups
    prNumber: number
    liftsLoading: boolean
    liftsLoadFailed: boolean
    selectedSnapshotId: string | null
    onSelect: (snapshotId: string) => void
}

/** Quarantined stories this run rendered exactly as their baseline, grouped by whether a lift is requested. */
export function CleanQuarantinedSnapshots({
    groups,
    prNumber,
    liftsLoading,
    liftsLoadFailed,
    selectedSnapshotId,
    onSelect,
}: CleanQuarantinedSnapshotsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 px-3 pb-3" data-attr="visual-review-clean-quarantined">
            <div className="text-xs text-muted">
                These quarantined stories matched their baseline in this run. Select one to lift its quarantine when #
                {prNumber} merges.
            </div>
            {liftsLoading ? (
                <LemonSkeleton className="h-4 w-1/3" />
            ) : liftsLoadFailed ? (
                <div className="text-xs text-muted" data-attr="visual-review-clean-quarantined-error">
                    Couldn't load the quarantines and lift requests of this pull request. Reload the page.
                </div>
            ) : (
                <>
                    {groups.liftRequested.length > 0 && (
                        <CleanQuarantinedStoryList
                            title={`Lift requested (${groups.liftRequested.length})`}
                            stories={groups.liftRequested}
                            selectedSnapshotId={selectedSnapshotId}
                            onSelect={onSelect}
                        />
                    )}
                    {groups.notRequested.length > 0 && (
                        <CleanQuarantinedStoryList
                            title={`Not requested (${groups.notRequested.length}), stay quarantined after the merge`}
                            stories={groups.notRequested}
                            selectedSnapshotId={selectedSnapshotId}
                            onSelect={onSelect}
                        />
                    )}
                </>
            )}
        </div>
    )
}
