import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderBulkMoveBar(): JSX.Element | null {
    const { selectedFiles } = useValues(workflowFoldersLogic)
    const { moveSelectedFiles, clearSelectedFiles } = useActions(workflowFoldersLogic)
    if (selectedFiles.length === 0) {
        return null
    }
    return (
        <div
            className="flex flex-wrap gap-2 items-center border rounded px-2 py-1 mb-2 bg-surface-secondary"
            data-attr="workflows-folder-bulk-move"
        >
            <span translate="no">{`${pluralize(selectedFiles.length, 'item')} selected`}</span>
            <LemonButton size="small" type="secondary" onClick={moveSelectedFiles}>
                Move to…
            </LemonButton>
            <LemonButton size="small" onClick={clearSelectedFiles}>
                Clear selection
            </LemonButton>
        </div>
    )
}
