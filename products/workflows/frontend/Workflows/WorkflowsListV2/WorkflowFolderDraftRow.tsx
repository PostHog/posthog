import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { WorkflowFolderRow } from './WorkflowFolderRow'
import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderDraftRow(): JSX.Element {
    const { folderDraft, folderDraftError, creatingFolder } = useValues(workflowFoldersLogic)
    const { setFolderDraftName, submitFolderDraft, cancelFolderDraft } = useActions(workflowFoldersLogic)
    const showError = !!folderDraft?.name.trim() && !!folderDraftError
    return (
        <WorkflowFolderRow icon={<IconFolder />}>
            <LemonInput
                size="small"
                autoFocus
                placeholder="Folder name"
                aria-label="New folder name"
                value={folderDraft?.name ?? ''}
                onChange={setFolderDraftName}
                onKeyDown={(event) => {
                    if (event.nativeEvent.isComposing || event.keyCode === 229) {
                        return
                    }
                    if (event.key === 'Enter') {
                        submitFolderDraft()
                    } else if (event.key === 'Escape') {
                        cancelFolderDraft()
                    }
                }}
                onBlur={() => !folderDraft?.name.trim() && cancelFolderDraft()}
                status={showError ? 'danger' : 'default'}
                disabled={creatingFolder}
                data-attr="workflows-new-folder-name"
            />
            {showError && <span className="text-danger text-xs truncate">{folderDraftError}</span>}
        </WorkflowFolderRow>
    )
}
