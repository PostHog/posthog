import { isSendingStopped, selectedSenders, senderDomain } from 'scenes/hog-functions/email-templater/emailSenderFields'

import type { IntegrationType } from '~/types'

import type { HogFlow } from './hogflows/types'

export interface StoppedSenderSteps {
    domains: string[]
    senderId: number
    stepIds: string[]
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
        const from = action.type === 'function_email' ? action.config.inputs?.email?.value?.from : null
        const senders = selectedSenders(typeof from === 'object' && from ? from : {}, integrations).filter(
            isSendingStopped
        )
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
        ? `switch ${those} to the PostHog test sender`
        : `add another sender and switch ${those} to it`
}
