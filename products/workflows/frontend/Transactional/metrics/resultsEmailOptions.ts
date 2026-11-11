import type { TransactionalEmailStatsRowApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MessageTemplate } from '../../TemplateLibrary/types'

export interface ResultsEmailOption {
    workflowId: string
    name: string
    sent: number
}

/** Transactional emails for the "What happened after" picker, busiest in the period first. */
export function buildResultsEmailOptions(
    templates: MessageTemplate[],
    templateStats: TransactionalEmailStatsRowApi[] | null
): ResultsEmailOption[] {
    const sentByTemplate = new Map((templateStats ?? []).map((row) => [row.key, row.sent]))
    return templates
        .filter((template) => template.transactional_hog_flow_id)
        .map((template) => ({
            workflowId: template.transactional_hog_flow_id as string,
            name: template.name || 'Unnamed email',
            sent: sentByTemplate.get(template.id) ?? 0,
        }))
        .sort((a, b) => b.sent - a.sent || a.name.localeCompare(b.name))
}
