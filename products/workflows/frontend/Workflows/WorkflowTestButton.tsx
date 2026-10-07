import { useActions, useValues } from 'kea'

import { IconTestTube } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { testEmailRecipientLogic } from './hogflows/panel/testing/testEmailRecipientLogic'
import { workflowLogic } from './workflowLogic'

export function WorkflowTestButton(): JSX.Element | null {
    const { workflow, hasUnsavedChanges, workflowUserAccessLevel, logicProps } = useValues(workflowLogic)
    const { testingV2Enabled } = useValues(testEmailRecipientLogic)
    const { openTestPane } = useActions(workflowLogic)

    if (!testingV2Enabled) {
        return null
    }

    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        logicProps.id === 'new' ? undefined : (workflowUserAccessLevel ?? undefined)
    )
    const isMainAction =
        workflow?.status === 'draft' && !hasUnsavedChanges && !logicProps.editTemplateId && !accessDisabledReason

    return (
        <LemonButton
            type={isMainAction ? 'primary' : 'secondary'}
            size="small"
            icon={<IconTestTube />}
            onClick={openTestPane}
            disabledReason={accessDisabledReason}
            tooltip="Open the test panel and step through the workflow with a test event"
            data-attr="workflow-test"
        >
            Test
        </LemonButton>
    )
}
