import { useActions, useValues } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { IconSlack } from 'lib/lemon-ui/icons'

import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { latestSaveStamp, workflowLogic } from '../workflowLogic'
import { UNSAVED_CHANGES_REASON } from './shareDisabledReason'
import { ShareWorkflowPreviewLogicProps, shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

export function ShareWorkflowPreviewMenuBarItem({ id }: ShareWorkflowPreviewLogicProps): JSX.Element {
    const { workflow, originalWorkflow, workflowUserAccessLevel, hasUnsavedChanges } = useValues(workflowLogic)
    const { openModal } = useActions(shareWorkflowPreviewLogic({ id }))

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason: accessDisabledReason }) => {
                const disabledReason = accessDisabledReason ?? (hasUnsavedChanges ? UNSAVED_CHANGES_REASON : null)
                return (
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={() => openModal(workflow, latestSaveStamp(originalWorkflow) ?? workflow.updated_at)}
                        disabled={!!disabledReason}
                        tooltip={disabledReason ?? undefined}
                        data-attr="workflow-menubar-share-preview"
                    >
                        <IconSlack />
                        Share preview to Slack
                    </SceneMenuBarItem>
                )
            }}
        </AccessControlAction>
    )
}
