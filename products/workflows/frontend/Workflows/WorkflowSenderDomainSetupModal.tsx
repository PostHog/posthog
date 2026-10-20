import { useActions, useValues } from 'kea'

import { EmailDomainSetupModal } from '../Channels/EmailDomain/EmailDomainSetupModal'
import { workflowLogic } from './workflowLogic'

const ENABLED_STATUSES = ['active', 'waiting_for_domain']

/** The email domain setup, over the workflow whose status bar opened it. */
export function WorkflowSenderDomainSetupModal(): JSX.Element | null {
    const { senderDomainSetup, originalWorkflow, enableFromSenderDomainSetupDisabledReason } = useValues(workflowLogic)
    const { closeSenderDomainSetup, enableFromSenderDomainSetup } = useActions(workflowLogic)

    if (!senderDomainSetup || !originalWorkflow) {
        return null
    }

    return (
        <EmailDomainSetupModal
            integrationId={senderDomainSetup.integrationId}
            entry="workflow"
            workflow={{
                name: originalWorkflow.name,
                enabled: ENABLED_STATUSES.includes(originalWorkflow.status),
                enableDisabledReason: enableFromSenderDomainSetupDisabledReason,
                onEnable: enableFromSenderDomainSetup,
                onBack: closeSenderDomainSetup,
            }}
            onComplete={closeSenderDomainSetup}
            onClose={closeSenderDomainSetup}
        />
    )
}
