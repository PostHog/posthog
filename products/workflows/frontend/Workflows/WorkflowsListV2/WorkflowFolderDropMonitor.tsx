import { useActions } from 'kea'

import { LemonTreeDndMonitor } from 'lib/lemon-ui/LemonTree/LemonTreeDndMonitor'

import { WORKFLOW_FILES_DRAG_SCOPE, WORKFLOW_FOLDER_DROP_SCOPES } from './workflowFolderDragScopes'
import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderDropMonitor(): JSX.Element {
    const { dropFile } = useActions(workflowFoldersLogic)
    return (
        <LemonTreeDndMonitor
            scope={WORKFLOW_FILES_DRAG_SCOPE}
            onDragEnd={({ active, over }) => {
                if (over && WORKFLOW_FOLDER_DROP_SCOPES.includes(over.data.current?.treeScope)) {
                    dropFile(String(active.id), String(over.id))
                }
            }}
        >
            {null}
        </LemonTreeDndMonitor>
    )
}
