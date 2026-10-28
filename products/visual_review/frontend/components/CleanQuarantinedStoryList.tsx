import { LemonButton } from '@posthog/lemon-ui'

import type { CleanQuarantinedStory } from '../lib/liftOnMerge'

function storyNote(story: CleanQuarantinedStory): string | null {
    if (story.expectsOtherPicture) {
        return 'The request expects a different picture than this run rendered. Request the lift again.'
    }
    return story.liftRequest?.state === 'pending' ? story.liftRequest.detail : story.quarantineReason
}

/** One group of clean quarantined stories. Selecting a story opens it with its lift controls. */
export function CleanQuarantinedStoryList({
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
