import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export interface WorkflowRowMenuOverlayProps {
    status: string
    userAccessLevel?: AccessControlLevel
    onToggleStatus: () => void
    onDuplicate: () => void
    onArchive: () => void
    onRestore: () => void
    onDelete: () => void
}

/** The actions of one workflow row, shared by both workflows lists. */
export function WorkflowRowMenuOverlay({
    status,
    userAccessLevel,
    onToggleStatus,
    onDuplicate,
    onArchive,
    onRestore,
    onDelete,
}: WorkflowRowMenuOverlayProps): JSX.Element {
    return (
        <>
            {status !== 'archived' && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={userAccessLevel}
                >
                    <LemonButton
                        data-attr="workflow-edit"
                        fullWidth
                        status={status === 'draft' ? 'default' : 'danger'}
                        onClick={onToggleStatus}
                        tooltip={
                            status === 'draft'
                                ? 'Enables the workflow to start sending messages'
                                : 'Disables the workflow from sending any new messages. In-progress workflows will end immediately.'
                        }
                    >
                        {status === 'draft' ? 'Enable' : 'Disable'}
                    </LemonButton>
                </AccessControlAction>
            )}
            <LemonButton data-attr="workflow-duplicate" fullWidth onClick={onDuplicate}>
                Duplicate
            </LemonButton>
            <LemonDivider />
            <AccessControlAction
                resourceType={AccessControlResourceType.Workflow}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={userAccessLevel}
            >
                <LemonButton
                    data-attr="workflow-archive-restore"
                    fullWidth
                    status={status === 'archived' ? 'default' : 'danger'}
                    onClick={status === 'archived' ? onRestore : onArchive}
                >
                    {status === 'archived' ? 'Restore' : 'Archive'}
                </LemonButton>
            </AccessControlAction>
            {status === 'archived' && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={userAccessLevel}
                >
                    <LemonButton data-attr="workflow-delete" fullWidth status="danger" onClick={onDelete}>
                        Delete
                    </LemonButton>
                </AccessControlAction>
            )}
        </>
    )
}
