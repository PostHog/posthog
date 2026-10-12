import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { getBranchLabel } from '../hogflows/branchLabel'
import { isEmailAction } from '../hogflows/steps/types'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../hogflows/types'

const SLACK_PRESERVED_INDENT = '\u2003'

const TRIGGER_DESCRIPTIONS: Record<string, string> = {
    manual: 'run manually',
    webhook: 'webhook',
    tracking_pixel: 'tracking pixel',
    schedule: 'on a schedule',
    batch: 'batch run',
    'data-warehouse-table': 'new rows in a data warehouse table',
    'data-warehouse-view': 'new rows in a data warehouse view',
    'internal-event': 'PostHog event',
}

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

interface WorkflowWalk {
    lines: string[]
    actionsInOrder: HogFlowAction[]
}

export function buildWorkflowOutline(workflow: HogFlow): string[] {
    return walkWorkflow(workflow).lines
}

export function listEmailSteps(
    workflow: HogFlow,
    sendersByIntegrationId: EmailSendersByIntegrationId = {}
): EmailStep[] {
    return walkWorkflow(workflow)
        .actionsInOrder.filter(isEmailAction)
        .map((action) => toEmailStep(action, sendersByIntegrationId))
}

function walkWorkflow(workflow: HogFlow): WorkflowWalk {
    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const edgesFrom = new Map<string, HogFlowEdge[]>()
    for (const edge of workflow.edges) {
        edgesFrom.set(edge.from, [...(edgesFrom.get(edge.from) ?? []), edge])
    }
    const isExit = (actionId: string): boolean => actionsById.get(actionId)?.type === 'exit'
    const walk: WorkflowWalk = { lines: [], actionsInOrder: [] }
    const visited = new Set<string>()

    const walkPath = (startId: string | undefined, depth: number): void => {
        const indent = SLACK_PRESERVED_INDENT.repeat(depth)
        let actionId = startId
        while (actionId) {
            const action = actionsById.get(actionId)
            if (!action || action.type === 'exit') {
                return
            }
            if (visited.has(action.id)) {
                walk.lines.push(`${indent}• Continues at "${action.name}"`)
                return
            }
            visited.add(action.id)
            walk.actionsInOrder.push(action)
            walk.lines.push(`${indent}• ${describeAction(action)}`)

            const outgoing = edgesFrom.get(action.id) ?? []
            const next = outgoing.find((edge) => edge.type === 'continue')
            const branches = outgoing
                .filter((edge) => edge.type === 'branch')
                .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
            if (branches.length === 0) {
                actionId = next?.to
                continue
            }
            for (const branch of branches) {
                walk.lines.push(`${indent}${SLACK_PRESERVED_INDENT}↳ ${describeBranch(action, branch)}`)
                walkPath(branch.to, depth + 2)
            }
            if (next && !isExit(next.to)) {
                walk.lines.push(`${indent}${SLACK_PRESERVED_INDENT}↳ No match`)
                walkPath(next.to, depth + 2)
            }
            return
        }
    }

    walkPath(workflow.actions.find((action) => action.type === 'trigger')?.id, 0)
    return walk
}

function describeAction(action: HogFlowAction): string {
    switch (action.type) {
        case 'trigger':
            return `Trigger: ${describeTrigger(action)}`
        case 'function_email':
            return `${action.name}: email "${emailTemplateOf(action).subject ?? ''}"`
        case 'function_sms':
            return `${action.name}: SMS`
        case 'function_push':
            return `${action.name}: push notification`
        case 'delay':
            return `${action.name}: ${action.config.delay_duration ?? 'until a date'}`
        case 'wait_until_condition':
            return `${action.name}: up to ${action.config.max_wait_duration}`
        default:
            return action.name
    }
}

function describeTrigger(action: Extract<HogFlowAction, { type: 'trigger' }>): string {
    const config = action.config
    if (config.type !== 'event') {
        return TRIGGER_DESCRIPTIONS[config.type] ?? config.type
    }
    const filters = (config.filters ?? {}) as {
        events?: { id?: string | number | null; name?: string | null }[]
        actions?: { id?: string | number | null; name?: string | null }[]
    }
    const names = [...(filters.events ?? []), ...(filters.actions ?? [])]
        .map((entity) => entity.name || (entity.id == null ? '' : String(entity.id)))
        .filter((name) => !!name)
    return names.length ? names.join(', ') : 'any event'
}

function describeBranch(action: HogFlowAction, edge: HogFlowEdge): string {
    const label = getBranchLabel(action, edge)
    if (action.type !== 'random_cohort_branch') {
        return label
    }
    const percentage = action.config.cohorts?.[edge.index ?? 0]?.percentage
    return percentage === undefined ? label : `${label} (${percentage}%)`
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
    const name = from.name ?? connectedSender?.name
    const email = from.email ?? connectedSender?.email
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
