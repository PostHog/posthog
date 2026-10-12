import { useActions, useValues } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { IconSlack } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { ShareWorkflowPreviewLogicProps, shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

export function ShareWorkflowPreviewPanelButton({ id }: ShareWorkflowPreviewLogicProps): JSX.Element {
    const { workflow, workflowUserAccessLevel } = useValues(workflowLogic)
    const { openModal } = useActions(shareWorkflowPreviewLogic({ id }))

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => (
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
            )}
        </AccessControlAction>
    )
}
