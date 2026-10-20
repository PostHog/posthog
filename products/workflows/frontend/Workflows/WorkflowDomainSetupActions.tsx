import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { BigAction } from '../Channels/EmailDomain/components/BigAction'
import { emailDomainLogic } from '../Channels/EmailDomain/emailDomainLogic'
import { emailDomainSenderLogic } from '../Channels/EmailDomain/emailDomainSenderLogic'
import { workflowLogic } from './workflowLogic'

const ENABLED_STATUSES = ['active', 'waiting_for_domain']

function lead(enabled: boolean, disabledReason: string | null, verifying: boolean, domain: string): string {
    if (enabled) {
        return verifying ? `It's on and starts sending once ${domain} is verified.` : "It's on."
    }
    if (disabledReason) {
        return disabledReason
    }
    return verifying
        ? `It starts sending once ${domain} is verified.`
        : `${domain} is verified. Turn the workflow on to start sending.`
}

/** The workflow's own next step inside the domain setup it opened, in place of the workflow suggestions. */
export function WorkflowDomainSetupActions(): JSX.Element | null {
    const { originalWorkflow, enableFromSenderDomainSetupDisabledReason, senderDomainSetup } = useValues(workflowLogic)
    const { enableFromSenderDomainSetup, closeSenderDomainSetup } = useActions(workflowLogic)
    const { phase } = useValues(emailDomainLogic)
    const { domain, fromAddress } = useValues(emailDomainSenderLogic)

    if (!originalWorkflow) {
        return null
    }
    const verifying = phase === 'verifying'
    const enabled = ENABLED_STATUSES.includes(originalWorkflow.status)
    const offersEnable = !enabled && !enableFromSenderDomainSetupDisabledReason
    return (
        <LemonCard hoverEffect={false} className="rounded-xl @md:p-8 flex flex-col gap-5">
            <div className="flex flex-col gap-1 min-w-0">
                <span className="text-xs uppercase tracking-wide text-secondary">Your workflow</span>
                <h2 className="m-0 text-xl font-semibold break-words">{originalWorkflow.name}</h2>
                <p className="m-0 text-sm text-secondary break-words">
                    {lead(enabled, enableFromSenderDomainSetupDisabledReason, verifying, domain ?? 'the domain')}
                </p>
                {senderDomainSetup?.filledEmptySenders && fromAddress && (
                    <p className="m-0 text-sm text-secondary break-words">
                        Your workflow now sends from <strong>{fromAddress}</strong>.
                    </p>
                )}
            </div>
            <div className="flex flex-col gap-2">
                {offersEnable && (
                    <BigAction onClick={enableFromSenderDomainSetup} data-attr="email-domain-workflow-enable">
                        {verifying ? 'Enable and send once verified' : 'Enable workflow'}
                    </BigAction>
                )}
                <LemonButton
                    type={offersEnable ? 'tertiary' : 'secondary'}
                    size="large"
                    fullWidth
                    center
                    onClick={closeSenderDomainSetup}
                    data-attr="email-domain-workflow-back"
                >
                    Back to workflow
                </LemonButton>
            </div>
        </LemonCard>
    )
}
