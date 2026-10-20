import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'
import { urls } from 'scenes/urls'

import { isEmailAction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'
import { unverifiedSenderDomains } from './unverifiedSenderDomains'

export type SenderDomainNotice =
    | { stage: 'no_domain'; url: string }
    | { stage: 'unverified' | 'waiting'; domains: string[]; url: string }

function hasEmailStepWithoutSender(workflow: HogFlow): boolean {
    return workflow.actions.filter(isEmailAction).some((action) => {
        const sender: EmailTemplateFrom | undefined = action.config.inputs.email?.value?.from
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
