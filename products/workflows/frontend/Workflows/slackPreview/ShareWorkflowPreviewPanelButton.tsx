import { useActions, useValues } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { IconSlack } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { UNSAVED_CHANGES_REASON } from './shareDisabledReason'
import { ShareWorkflowPreviewLogicProps, shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

export function ShareWorkflowPreviewPanelButton({ id }: ShareWorkflowPreviewLogicProps): JSX.Element {
    const { workflow, workflowUserAccessLevel, hasUnsavedChanges } = useValues(workflowLogic)
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
                    <ButtonPrimitive
                        menuItem
                        onClick={() => openModal(workflow)}
                        disabled={!!disabledReason}
                        tooltip={disabledReason ?? undefined}
                        data-attr="workflow-share-preview-btn"
                    >
                        <IconSlack />
                        Share preview to Slack
                    </ButtonPrimitive>
                )
            }}
        </AccessControlAction>
    )
}
