import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'
import { urls } from 'scenes/urls'

import { isEmailAction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'
import { unverifiedSenderDomains } from './unverifiedSenderDomains'

export type SenderDomainNotice =
    | { stage: 'no_domain'; url: string }
    | { stage: 'unverified' | 'waiting'; domains: string[]; url: string }

function chosenSenderIds(sender: EmailTemplateFrom | undefined): number[] {
    return sender?.integrationIds?.length ? sender.integrationIds : sender?.integrationId ? [sender.integrationId] : []
}

function hasEmailStepWithoutSender(workflow: HogFlow, existingSenderIds: ReadonlySet<number> | null): boolean {
    return workflow.actions.filter(isEmailAction).some((action) => {
        const senderIds = chosenSenderIds(action.config.inputs.email?.value?.from)
        return existingSenderIds
            ? !senderIds.some((senderId) => existingSenderIds.has(senderId))
            : senderIds.length === 0
    })
}

export function senderDomainNotice(
    workflow: HogFlow,
    savedWorkflow: HogFlow,
    existingSenderIds: ReadonlySet<number> | null
): SenderDomainNotice | null {
    if (hasEmailStepWithoutSender(workflow, existingSenderIds)) {
        return { stage: 'no_domain', url: urls.workflows('channels') }
    }
    const domains = unverifiedSenderDomains(savedWorkflow)
    if (domains.length === 0) {
        return null
    }
    const stage = savedWorkflow.status === 'waiting_for_domain' ? 'waiting' : 'unverified'
    return { stage, domains, url: urls.workflows('channels') }
}
