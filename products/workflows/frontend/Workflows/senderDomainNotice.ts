import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'
import { urls } from 'scenes/urls'

import type { HogFlow, HogFlowAction } from './hogflows/types'
import { unverifiedSenderDomains } from './unverifiedSenderDomains'

export type SenderDomainNotice =
    | { stage: 'no_domain'; url: string }
    | { stage: 'unverified' | 'waiting'; domains: string[]; url: string }

function emailSender(action: HogFlowAction): EmailTemplateFrom | undefined {
    return (action.config as { inputs?: { email?: { value?: { from?: EmailTemplateFrom } } } }).inputs?.email?.value
        ?.from
}

function hasEmailStepWithoutSender(workflow: HogFlow): boolean {
    return workflow.actions.some((action) => {
        if (action.type !== 'function_email') {
            return false
        }
        const sender = emailSender(action)
        return !sender?.integrationId && !sender?.integrationIds?.length
    })
}

export function senderDomainNotice(workflow: HogFlow, savedWorkflow: HogFlow): SenderDomainNotice | null {
    if (hasEmailStepWithoutSender(workflow)) {
        return { stage: 'no_domain', url: urls.workflows('channels') }
    }
    const domains = unverifiedSenderDomains(savedWorkflow)
    if (domains.length === 0) {
        return null
    }
    const stage = savedWorkflow.status === 'waiting_for_domain' ? 'waiting' : 'unverified'
    return { stage, domains, url: urls.workflows('channels') }
}
