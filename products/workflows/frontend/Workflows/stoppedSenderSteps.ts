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
    if (action.type !== 'function_email' && !(action.type === 'function' && config?.template_id === 'template-email')) {
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

// Unsaved edits can delete or fix a broken step, so the button opens one the draft still has broken.
export function stepToChange(
    broken: StoppedSenderSteps,
    draft: Pick<HogFlow, 'actions'>,
    integrations: IntegrationType[] | null
): string | null {
    const brokenInDraft = stoppedSenderSteps(draft, integrations)?.stepIds ?? []
    return broken.stepIds.find((id) => brokenInDraft.includes(id)) ?? null
}

// A rotating step still delivers from its other senders, so only the emails from a stopped domain fail.
export function stoppedSenderMessage(broken: StoppedSenderSteps): string {
    const oneStep = broken.stepIds.length === 1
    const oneDomain = broken.domains.length === 1
    const steps = oneStep ? 'An email step' : `${broken.stepIds.length} email steps`
    const sendFrom = `${oneStep ? 'sends' : 'send'} from ${oneDomain ? 'it' : 'them'}`
    const domains = oneDomain ? "the domain's" : "the domains'"
    return `Sending stopped for ${broken.domains.join(', ')}. ${steps} in this workflow ${sendFrom}, and those emails fail until ${domains} DNS records are fixed. Fix your sending domain, or change the sender on ${oneStep ? 'that step' : 'those steps'}.`
}
