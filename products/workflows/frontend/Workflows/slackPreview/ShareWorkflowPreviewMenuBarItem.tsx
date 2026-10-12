import { useActions, useValues } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { IconSlack } from 'lib/lemon-ui/icons'

import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { ShareWorkflowPreviewLogicProps, shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

export function ShareWorkflowPreviewMenuBarItem({ id }: ShareWorkflowPreviewLogicProps): JSX.Element {
    const { workflow, workflowUserAccessLevel } = useValues(workflowLogic)
    const { openModal } = useActions(shareWorkflowPreviewLogic({ id }))

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => (
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => openModal(workflow)}
                    disabled={!!disabledReason}
                    tooltip={disabledReason ?? undefined}
                    data-attr="workflow-menubar-share-preview"
                >
                    <IconSlack />
                    Share preview to Slack
                </SceneMenuBarItem>
            )}
        </AccessControlAction>
    )
}
