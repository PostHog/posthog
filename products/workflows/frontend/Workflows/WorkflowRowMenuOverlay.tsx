import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WorkflowRowAction } from './workflowRowActions'

export interface WorkflowRowMenuOverlayProps {
    status: string
    userAccessLevel?: AccessControlLevel
    pendingAction?: WorkflowRowAction
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
    pendingAction,
    onToggleStatus,
    onDuplicate,
    onArchive,
    onRestore,
    onDelete,
}: WorkflowRowMenuOverlayProps): JSX.Element {
    const pendingState = (action: WorkflowRowAction): { loading: boolean; disabledReason?: string } => ({
        loading: pendingAction === action,
        disabledReason: pendingAction && pendingAction !== action ? 'Wait for the current change to finish' : undefined,
    })
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
                        {...pendingState('toggle')}
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
            <LemonButton data-attr="workflow-duplicate" fullWidth onClick={onDuplicate} {...pendingState('duplicate')}>
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
                    {...pendingState(status === 'archived' ? 'restore' : 'archive')}
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
                    <LemonButton
                        data-attr="workflow-delete"
                        fullWidth
                        status="danger"
                        onClick={onDelete}
                        {...pendingState('delete')}
                    >
                        Delete
                    </LemonButton>
                </AccessControlAction>
            )}
        </>
    )
}
