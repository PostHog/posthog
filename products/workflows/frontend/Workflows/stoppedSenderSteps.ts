import { isSendingStopped, selectedSenders, senderDomain } from 'scenes/hog-functions/email-templater/emailSenderFields'
import type { EmailTemplateFrom } from 'scenes/hog-functions/email-templater/types'

import type { IntegrationType } from '~/types'

import { sandboxTakesStepId } from './hogflows/steps/email/emailStepVariants'
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
    const { integrationId, integrationIds = [] } = from as { integrationId?: unknown; integrationIds?: unknown }
    // Sending rejects a step without a sender ID, or with anything but sender IDs in its rotation list.
    if (
        typeof integrationId !== 'number' ||
        !Array.isArray(integrationIds) ||
        !integrationIds.every((id): id is number => typeof id === 'number')
    ) {
        return {}
    }
    return integrationIds.length > 0 ? { integrationIds } : { integrationId }
}

// A rotating step counts when any of its senders stopped, because the emails it sends from that sender fail.
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

export interface RepairTarget {
    stepId: string | null
    testSenderTakesSteps: boolean
}

// Unsaved edits can delete or fix a broken step, so the target follows the draft until it fixes them all.
export function repairTarget(
    broken: StoppedSenderSteps,
    live: Pick<HogFlow, 'actions'>,
    draft: Pick<HogFlow, 'actions'>,
    integrations: IntegrationType[] | null
): RepairTarget {
    const brokenInDraft = stoppedSenderSteps(draft, integrations)?.stepIds ?? []
    const stepIds = broken.stepIds.filter((id) => brokenInDraft.includes(id))
    return stepIds.length > 0
        ? { stepId: stepIds[0], testSenderTakesSteps: testSenderTakesSteps(draft, stepIds) }
        : { stepId: null, testSenderTakesSteps: testSenderTakesSteps(live, broken.stepIds) }
}

// Only an email step's From picker offers the test sender, and only for step IDs it can take.
function testSenderTakesSteps(workflow: Pick<HogFlow, 'actions'>, stepIds: string[]): boolean {
    return workflow.actions.every(
        (action) => !stepIds.includes(action.id) || (action.type === 'function_email' && sandboxTakesStepId(action))
    )
}

// A rotating step still delivers from its other senders, so only the emails from a stopped domain fail.
export function stoppedSenderMessage(broken: StoppedSenderSteps, nextStep: string): string {
    const oneStep = broken.stepIds.length === 1
    const oneDomain = broken.domains.length === 1
    const steps = oneStep ? 'An email step' : `${broken.stepIds.length} email steps`
    const sendFrom = `${oneStep ? 'sends' : 'send'} from ${oneDomain ? 'it' : 'them'}`
    const domains = oneDomain ? "the domain's" : "the domains'"
    return `Sending stopped for ${broken.domains.join(', ')}. ${steps} in this workflow ${sendFrom}, and those emails fail until ${domains} DNS records are fixed. Fix your sending domain, or ${nextStep}.`
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
