import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import { isEmailAction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'
import { unverifiedSenderDomains } from './unverifiedSenderDomains'

export type SenderDomainNotice =
    | { stage: 'no_domain'; url: string }
    | { stage: 'unverified' | 'waiting'; domains: string[]; url: string }

function chosenSenderIds(sender: EmailTemplateFrom | undefined): number[] {
    return sender?.integrationIds?.length ? sender.integrationIds : sender?.integrationId ? [sender.integrationId] : []
}

function hasEmailStepWithoutSender(workflow: HogFlow, emailSenders: IntegrationType[]): boolean {
    const existingSenderIds = new Set(emailSenders.map(({ id }) => id))
    return workflow.actions.filter(isEmailAction).some((action) => {
        const senderIds = chosenSenderIds(action.config.inputs.email?.value?.from)
        return !senderIds.some((senderId) => existingSenderIds.has(senderId))
    })
}

function projectDomainNotice(workflow: HogFlow, emailSenders: IntegrationType[]): SenderDomainNotice | null {
    const hasVerifiedSender = emailSenders.some(({ config }) => config.verified === true)
    if (hasVerifiedSender || !hasEmailStepWithoutSender(workflow, emailSenders)) {
        return null
    }
    const pendingDomains: string[] = [...new Set(emailSenders.map(({ config }) => config.domain))]
    return pendingDomains.length > 0
        ? { stage: 'unverified', domains: pendingDomains, url: urls.workflows('channels') }
        : { stage: 'no_domain', url: urls.workflows('channels') }
}

export function senderDomainNotice(
    workflow: HogFlow,
    savedWorkflow: HogFlow,
    emailSenders: IntegrationType[] | null
): SenderDomainNotice | null {
    const domains = unverifiedSenderDomains(savedWorkflow)
    if (domains.length > 0) {
        const stage = savedWorkflow.status === 'waiting_for_domain' ? 'waiting' : 'unverified'
        return { stage, domains, url: urls.workflows('channels') }
    }
    return emailSenders ? projectDomainNotice(workflow, emailSenders) : null
}
