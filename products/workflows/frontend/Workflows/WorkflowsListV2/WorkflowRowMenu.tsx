import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { AccessControlLevel } from '~/types'
import { AccessControlResourceType } from '~/types'

import { WorkflowRowMenuOverlay } from '../WorkflowRowMenuOverlay'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowListRow } from './workflowListRows'
import { workflowsListV2Logic } from './workflowsListV2Logic'

export function WorkflowRowMenu({ row }: { row: WorkflowListRow }): JSX.Element {
    const { pendingRowActions, projectFilesEnabled } = useValues(workflowsListV2Logic)
    const { movingWorkflowId } = useValues(workflowFoldersLogic)
    const { moveWorkflowToFolder } = useActions(workflowFoldersLogic)
    const { toggleWorkflowStatus, duplicateWorkflow, archiveWorkflow, restoreWorkflow, deleteWorkflow } =
        useActions(workflowsListV2Logic)
    return (
        <More
            overlay={
                <>
                    {projectFilesEnabled && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={(row.workflow.user_access_level as AccessControlLevel | null) ?? undefined}
                        >
                            <LemonButton
                                fullWidth
                                onClick={() => moveWorkflowToFolder(row.id)}
                                loading={movingWorkflowId === row.id}
                                disabledReason={
                                    movingWorkflowId && movingWorkflowId !== row.id
                                        ? 'Wait for the current move'
                                        : undefined
                                }
                                data-attr="workflow-move-to"
                            >
                                Move to
                            </LemonButton>
                        </AccessControlAction>
                    )}
                    <WorkflowRowMenuOverlay
                        status={row.workflow.status}
                        userAccessLevel={(row.workflow.user_access_level as AccessControlLevel | null) ?? undefined}
                        pendingAction={pendingRowActions[row.id]}
                        onToggleStatus={() => toggleWorkflowStatus(row)}
                        onDuplicate={() => duplicateWorkflow(row)}
                        onArchive={() => archiveWorkflow(row)}
                        onRestore={() => restoreWorkflow(row)}
                        onDelete={() => deleteWorkflow(row)}
                    />
                </>
            }
        />
    )
}
