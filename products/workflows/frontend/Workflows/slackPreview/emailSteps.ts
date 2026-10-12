import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { isEmailAction } from '../hogflows/steps/types'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../hogflows/types'

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
    return actionsInRunOrder(workflow)
        .filter(isEmailAction)
        .map((action) => toEmailStep(action, sendersByIntegrationId))
}

// The order the server's outline lists steps in: depth first from the trigger, each branch in index
// order before the step that follows when no branch matches. Steps the trigger cannot reach are left out.
function actionsInRunOrder(workflow: HogFlow): HogFlowAction[] {
    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const nextSteps = (actionId: string): HogFlowEdge[] => {
        const outgoing = workflow.edges.filter((edge) => edge.from === actionId)
        const branches = outgoing
            .filter((edge) => edge.type === 'branch')
            .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
        return [...branches, ...outgoing.filter((edge) => edge.type === 'continue')]
    }
    const visited = new Set<string>()
    const ordered: HogFlowAction[] = []
    const visit = (actionId: string | undefined): void => {
        const action = actionId ? actionsById.get(actionId) : undefined
        if (!action || visited.has(action.id)) {
            return
        }
        visited.add(action.id)
        ordered.push(action)
        nextSteps(action.id).forEach((edge) => visit(edge.to))
    }
    visit(workflow.actions.find((action) => action.type === 'trigger')?.id)
    return ordered
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
