import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderSelectAll(): JSX.Element {
    const { selectedFiles, selectableFiles } = useValues(workflowFoldersLogic)
    const { setSelectedFiles } = useActions(workflowFoldersLogic)
    const selectableIds = Object.keys(selectableFiles)
    const allSelected = selectedFiles.length > 0 && selectedFiles.length === selectableIds.length
    return (
        <LemonCheckbox
            aria-label="Select all movable items"
            checked={allSelected || (selectedFiles.length > 0 && 'indeterminate')}
            onChange={(checked) => setSelectedFiles(checked ? selectableIds : [])}
        />
    )
}
