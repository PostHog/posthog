import { useActions } from 'kea'

import { IconArrowLeft, IconFolder } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { WORKFLOW_FOLDER_CONTENTS_DROP_SCOPE } from './workflowFolderDragScopes'
import { WorkflowFolderRow } from './WorkflowFolderRow'
import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowFolderNavigationRow({
    kind,
    name,
    path,
    count,
}: {
    kind: 'folder' | 'up'
    name: string
    path: string
    count: number
}): JSX.Element {
    const { openFolder } = useActions(workflowFoldersLogic)
    return (
        <WorkflowFolderRow
            icon={kind === 'up' ? <IconArrowLeft /> : <IconFolder />}
            drop={{ id: `project://${path}`, scope: WORKFLOW_FOLDER_CONTENTS_DROP_SCOPE }}
        >
            <LemonButton
                size="small"
                noPadding
                className="flex-1 min-w-0"
                onClick={() => openFolder(path || null)}
                data-attr="workflows-folder-row"
            >
                <span className="truncate mr-1">{name}</span>
                {kind === 'folder' && (
                    <span className="text-secondary font-normal text-xs" translate="no">{`(${count})`}</span>
                )}
            </LemonButton>
        </WorkflowFolderRow>
    )
}
