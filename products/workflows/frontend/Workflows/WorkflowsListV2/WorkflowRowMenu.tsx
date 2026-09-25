import { useActions } from 'kea'

import { More } from 'lib/lemon-ui/LemonButton/More'

import { AccessControlLevel } from '~/types'

import { WorkflowRowMenuOverlay } from '../WorkflowRowMenuOverlay'
import { WorkflowRow } from './workflowListRows'
import { workflowsListV2Logic } from './workflowsListV2Logic'

export function WorkflowRowMenu({ row }: { row: WorkflowRow }): JSX.Element {
    const { toggleWorkflowStatus, duplicateWorkflow, archiveWorkflow, restoreWorkflow, deleteWorkflow } =
        useActions(workflowsListV2Logic)
    return (
        <More
            overlay={
                <WorkflowRowMenuOverlay
                    status={row.workflow.status}
                    userAccessLevel={(row.workflow.user_access_level as AccessControlLevel | null) ?? undefined}
                    onToggleStatus={() => toggleWorkflowStatus(row)}
                    onDuplicate={() => duplicateWorkflow(row)}
                    onArchive={() => archiveWorkflow(row)}
                    onRestore={() => restoreWorkflow(row)}
                    onDelete={() => deleteWorkflow(row)}
                />
            }
        />
    )
}
