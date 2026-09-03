import type { HogFlowAction, HogFlowTemplate } from '../hogflows/types'

const TRIGGER_LABELS: Record<string, string> = {
    event: 'Starts on an event',
    'internal-event': 'Starts on an event',
    webhook: 'Starts on a webhook',
    manual: 'Starts manually',
    schedule: 'Starts on a schedule',
    tracking_pixel: 'Starts on a tracking pixel',
    batch: 'Starts for an audience',
    'data-warehouse-table': 'Starts on warehouse data',
    'data-warehouse-view': 'Starts on warehouse data',
}

const SCOPE_LABELS: Record<string, string> = {
    organization: 'Organization',
    team: 'Team',
}

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export interface TemplateTrigger {
    type: string
    label: string
}

export function getTemplateTrigger(template: Pick<HogFlowTemplate, 'trigger' | 'actions'>): TemplateTrigger | null {
    const triggerAction = template.actions?.find((action): action is TriggerAction => action.type === 'trigger')
    const type = triggerAction?.config.type ?? template.trigger?.type
    if (!type) {
        return null
    }
    return { type, label: TRIGGER_LABELS[type] ?? 'Starts on a trigger' }
}

// Global templates are the majority, so only the narrower scopes are worth a label.
export function getTemplateScopeLabel(scope: HogFlowTemplate['scope']): string | null {
    return scope ? (SCOPE_LABELS[scope] ?? null) : null
}
