import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { MERGE_LIMIT_REASON, MERGE_SOURCE_LIMIT } from './releaseMerge'
import { releaseMergeLogic } from './releaseMergeLogic'

export function ReleaseSelectionBar(): JSX.Element | null {
    const { candidates, canEditReleases } = useValues(releaseMergeLogic)
    const { setMergeOpen, setSelection } = useActions(releaseMergeLogic)

    if (!canEditReleases || !candidates.length) {
        return null
    }
    return (
        <div className="flex items-center gap-2" data-attr="release-selection-bar">
            <Text size="xs" variant="muted">{`${candidates.length} selected`}</Text>
            <Button
                size="sm"
                variant="outline"
                disabledReason={
                    candidates.length < 2
                        ? 'Select at least two releases to merge'
                        : candidates.length - 1 > MERGE_SOURCE_LIMIT
                          ? MERGE_LIMIT_REASON
                          : undefined
                }
                onClick={() => setMergeOpen(true)}
                data-attr="release-merge-open"
            >
                Merge
            </Button>
            <Button size="sm" variant="link" onClick={() => setSelection({})} data-attr="release-selection-clear">
                Clear
            </Button>
        </div>
    )
}
