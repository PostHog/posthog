import { useActions, useValues } from 'kea'

import { IconFolderPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowNewFolderButton({
    parent,
    iconOnly = false,
}: {
    parent: string
    iconOnly?: boolean
}): JSX.Element {
    const { creatingFolder } = useValues(workflowFoldersLogic)
    const { startFolderDraft } = useActions(workflowFoldersLogic)
    const label = `New folder in ${parent || 'the project root'}`
    return (
        <LemonButton
            size="xsmall"
            icon={<IconFolderPlus />}
            aria-label={label}
            tooltip={label}
            loading={creatingFolder}
            disabledReason={parent === 'Unfiled' ? 'Open a project folder to add a subfolder' : undefined}
            onClick={() => startFolderDraft(parent)}
            data-attr="workflows-new-folder"
        >
            {iconOnly ? null : 'New folder'}
        </LemonButton>
    )
}
