import { isSendingStopped, selectedSenders, senderDomain } from 'scenes/hog-functions/email-templater/emailSenderFields'
import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'

import type { IntegrationType } from '~/types'

import type { HogFlow, HogFlowAction } from './hogflows/types'

export interface StoppedSenderSteps {
    domains: string[]
    senderId: number
    stepIds: string[]
}

// Older email steps are saved as a plain function step on the email template.
function emailStepFrom(action: HogFlowAction): EmailTemplateFrom {
    const config = action.config as { template_id?: unknown; inputs?: Record<string, { value?: { from?: unknown } }> }
    if (action.type !== 'function_email' && config?.template_id !== 'template-email') {
        return {}
    }
    const from = config.inputs?.email?.value?.from
    if (typeof from !== 'object' || !from) {
        return {}
    }
    const { integrationId, integrationIds } = from as EmailTemplateFrom
    return {
        integrationId: typeof integrationId === 'number' ? integrationId : undefined,
        integrationIds: Array.isArray(integrationIds)
            ? integrationIds.filter((id): id is number => typeof id === 'number')
            : undefined,
    }
}

// A step that rotates through several senders counts when any of them stopped, because the emails it sends
// from that sender fail.
export function stoppedSenderSteps(
    workflow: Pick<HogFlow, 'actions'> | null,
    integrations: IntegrationType[] | null
): StoppedSenderSteps | null {
    const stepIds: string[] = []
    const stopped: IntegrationType[] = []
    for (const action of workflow?.actions ?? []) {
        const senders = selectedSenders(emailStepFrom(action), integrations).filter(isSendingStopped)
        if (senders.length > 0) {
            stepIds.push(action.id)
            stopped.push(...senders)
        }
    }
    if (stepIds.length === 0) {
        return null
    }
    return { domains: [...new Set(stopped.map(senderDomain))], senderId: stopped[0].id, stepIds }
}

// Names only the senders the step's From picker offers: it shows the test sender only when no own sender can send.
export function changeSenderAdvice(stepCount: number, otherSenderSends: boolean, canUseTestSender: boolean): string {
    const those = stepCount === 1 ? 'that step' : 'those steps'
    if (otherSenderSends) {
        return `change the sender on ${those} to another sender`
    }
    return canUseTestSender
        ? `switch ${those} to the PostHog test sender, which reaches only verified members of your organization`
        : `add another sender and switch ${those} to it`
}
