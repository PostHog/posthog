import { useActions, useValues } from 'kea'

import { EmailDomainSetupModal } from '../Channels/EmailDomain/EmailDomainSetupModal'
import { WorkflowDomainSetupActions } from './WorkflowDomainSetupActions'
import { workflowLogic } from './workflowLogic'

/** The email domain setup, over the workflow whose status bar opened it. */
export function WorkflowSenderDomainSetupModal(): JSX.Element | null {
    const { senderDomainSetup, originalWorkflow } = useValues(workflowLogic)
    const { closeSenderDomainSetup, fillEmptySendersFromDomainSetup } = useActions(workflowLogic)

    if (!senderDomainSetup || !originalWorkflow) {
        return null
    }
    return (
        <EmailDomainSetupModal
            integrationId={senderDomainSetup.integrationId}
            entry="workflow"
            surface="workflow_editor"
            description={`For the workflow ${originalWorkflow.name}`}
            next={<WorkflowDomainSetupActions />}
            onComplete={closeSenderDomainSetup}
            onClose={closeSenderDomainSetup}
            onSenderCreated={fillEmptySendersFromDomainSetup}
        />
    )
}
