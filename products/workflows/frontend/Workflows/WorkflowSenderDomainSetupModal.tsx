import { useActions, useValues } from 'kea'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { EmailDomainSetupModal } from '../Channels/EmailDomain/EmailDomainSetupModal'
import { workflowLogic } from './workflowLogic'

const ENABLED_STATUSES = ['active', 'waiting_for_domain']

/** The email domain setup, over the workflow whose status bar opened it. */
export function WorkflowSenderDomainSetupModal(): JSX.Element | null {
    const { senderDomainSetup, originalWorkflow, enableFromSenderDomainSetupDisabledReason } = useValues(workflowLogic)
    const { closeSenderDomainSetup, enableFromSenderDomainSetup } = useActions(workflowLogic)
    const { integrations } = useValues(integrationsLogic)

    if (!senderDomainSetup || !originalWorkflow) {
        return null
    }
    const { integrationId } = senderDomainSetup
    const integration = integrationId === null ? null : integrations?.find(({ id }) => id === integrationId)
    if (integration === undefined) {
        return null
    }

    return (
        <EmailDomainSetupModal
            integration={integration}
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
