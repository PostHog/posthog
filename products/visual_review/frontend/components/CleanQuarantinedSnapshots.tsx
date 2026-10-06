import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import type { CleanQuarantinedGroups, CleanQuarantinedStory } from '../lib/liftOnMerge'

interface CleanQuarantinedSnapshotsProps {
    groups: CleanQuarantinedGroups
    prNumber: number
    liftsLoading: boolean
    liftsLoadFailed: boolean
    selectedSnapshotId: string | null
    onSelect: (snapshotId: string) => void
}

function storyNote(story: CleanQuarantinedStory): string | null {
    if (story.expectsOtherPicture) {
        return 'The request expects a different picture than this run rendered. Request the lift again.'
    }
    return story.liftRequest?.state === 'pending' ? story.liftRequest.detail : story.quarantineReason
}

function StoryList({
    title,
    stories,
    selectedSnapshotId,
    onSelect,
}: {
    title: string
    stories: CleanQuarantinedStory[]
    selectedSnapshotId: string | null
    onSelect: (snapshotId: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <div className="text-xs font-semibold">{title}</div>
            {stories.map((story) => (
                <LemonButton
                    key={story.snapshot.id}
                    size="xsmall"
                    fullWidth
                    active={story.snapshot.id === selectedSnapshotId}
                    onClick={() => onSelect(story.snapshot.id)}
                    data-attr="visual-review-clean-quarantined-select"
                >
                    <span className="flex min-w-0 flex-col items-start text-xs font-normal">
                        <span className="max-w-full truncate font-mono">{story.snapshot.identifier}</span>
                        <span className={story.expectsOtherPicture ? 'text-warning-dark' : 'text-muted'}>
                            {storyNote(story)}
                        </span>
                    </span>
                </LemonButton>
            ))}
        </div>
    )
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
                    Couldn't load the lift requests of this pull request. Reload the page.
                </div>
            ) : (
                <>
                    {groups.liftRequested.length > 0 && (
                        <StoryList
                            title={`Lift requested (${groups.liftRequested.length})`}
                            stories={groups.liftRequested}
                            selectedSnapshotId={selectedSnapshotId}
                            onSelect={onSelect}
                        />
                    )}
                    {groups.notRequested.length > 0 && (
                        <StoryList
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
