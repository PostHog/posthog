import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { releaseMergeLogic } from './releaseMergeLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseMergeButton({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { canEditReleases, rows, selectionDisabledReason } = useValues(releaseMergeLogic)
    const { openMergeInto } = useActions(releaseMergeLogic)

    if (!canEditReleases || rows.length < 2) {
        return null
    }
    return (
        <Button
            variant="outline"
            disabledReason={selectionDisabledReason(row.id) ?? undefined}
            onClick={() => openMergeInto(row.id)}
            data-attr="release-merge-into"
        >
            Merge releases
        </Button>
    )
}
