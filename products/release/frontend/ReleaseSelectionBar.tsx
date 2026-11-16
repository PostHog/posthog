import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { releaseMergeLogic } from './releaseMergeLogic'

export function ReleaseSelectionBar(): JSX.Element | null {
    const { candidates } = useValues(releaseMergeLogic)
    const { setMergeOpen, setSelection } = useActions(releaseMergeLogic)

    if (!candidates.length) {
        return null
    }
    return (
        <div className="flex items-center gap-2" data-attr="release-selection-bar">
            <Text size="xs" variant="muted">{`${candidates.length} selected`}</Text>
            <Button
                size="sm"
                variant="outline"
                disabledReason={candidates.length < 2 ? 'Select at least two releases to merge' : undefined}
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
