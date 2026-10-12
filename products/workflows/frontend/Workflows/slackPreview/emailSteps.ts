import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { isEmailAction } from '../hogflows/steps/types'
import type { HogFlow, HogFlowAction } from '../hogflows/types'

export interface EmailStep {
    actionId: string
    stepName: string
    subject: string
    from: string
    preheader: string
    html: string
}

export interface EmailSender {
    name?: string
    email?: string
}

export type EmailSendersByIntegrationId = Record<number, EmailSender>

type EmailAction = Extract<HogFlowAction, { type: 'function_email' }>

export function listEmailSteps(
    workflow: HogFlow,
    sendersByIntegrationId: EmailSendersByIntegrationId = {}
): EmailStep[] {
    return workflow.actions.filter(isEmailAction).map((action) => toEmailStep(action, sendersByIntegrationId))
}

function emailTemplateOf(action: EmailAction): Partial<EmailTemplate> {
    return (action.config.inputs.email?.value ?? {}) as Partial<EmailTemplate>
}

function formatSender(
    from: EmailTemplate['from'] | undefined,
    sendersByIntegrationId: EmailSendersByIntegrationId
): string {
    if (!from || typeof from === 'string') {
        return from ?? ''
    }
    const connectedSender = from.integrationId ? sendersByIntegrationId[from.integrationId] : undefined
    const name = from.name || connectedSender?.name
    const email = from.email || connectedSender?.email
    if (!email) {
        return name ?? ''
    }
    return name ? `${name} <${email}>` : email
}

function toEmailStep(action: EmailAction, sendersByIntegrationId: EmailSendersByIntegrationId): EmailStep {
    const template = emailTemplateOf(action)
    return {
        actionId: action.id,
        stepName: action.name,
        subject: template.subject ?? '',
        from: formatSender(template.from, sendersByIntegrationId),
        preheader: template.preheader ?? '',
        html: template.html ?? '',
    }
}
