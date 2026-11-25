import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'
import type { MessageCategory } from './optOutCategoriesLogic'

// Mirrors the save rule in the workflows API: workflow emails are marketing email, except support replies.
const SUPPORT_EVENT_PREFIX = '$conversation_'
const SUPPORT_TRIGGER_TYPES = ['event', 'internal-event']
const EMAIL_STEP_TYPES = ['function_email', 'email_sandbox']

export function triggersOnlyOnSupportEvents(workflow: Pick<HogFlow, 'actions'>): boolean {
    const trigger = workflow.actions.find((action) => action.type === 'trigger')
    const config = trigger?.config as { type?: string; filters?: { events?: unknown[]; actions?: unknown[] } }
    const events = config?.filters?.events ?? []
    return (
        SUPPORT_TRIGGER_TYPES.includes(config?.type ?? '') &&
        events.length > 0 &&
        !config.filters?.actions?.length &&
        events.every((event) => {
            const entry = event as { type?: string; id?: unknown }
            return entry?.type === 'events' && String(entry.id ?? '').startsWith(SUPPORT_EVENT_PREFIX)
        })
    )
}

export function canPickTransactionalCategory(
    action: HogFlowAction,
    workflow: Pick<HogFlow, 'actions'>,
    categories: MessageCategory[]
): boolean {
    if (!EMAIL_STEP_TYPES.includes(action.type)) {
        return true
    }
    const config = action.config as { message_category_id?: string | null; message_category_type?: string | null }
    const selected = categories.find((category) => category.id === config.message_category_id)
    return (
        config.message_category_type === 'transactional' ||
        selected?.category_type === 'transactional' ||
        triggersOnlyOnSupportEvents(workflow)
    )
}
