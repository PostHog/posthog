import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'
import type { MessageCategory } from './optOutCategoriesLogic'

// Mirrors the save rule in the workflows API: workflow emails are marketing email, except support replies. Keep in step
// with SUPPORT_EVENTS in products/workflows/backend/services/transactional_steps.py.
const SUPPORT_EVENTS = new Set([
    '$conversation_ticket_created',
    '$conversation_ticket_status_changed',
    '$conversation_ticket_priority_changed',
    '$conversation_ticket_assigned',
    '$conversation_ticket_tag_added',
    '$conversation_message_sent',
    '$conversation_private_message_sent',
    '$conversation_message_received',
])
const EMAIL_STEP_TYPES = ['function_email', 'email_sandbox']

type StepConfig = { message_category_id?: string | null; message_category_type?: string | null }

export function triggersOnlyOnSupportEvents(workflow: Pick<HogFlow, 'actions'>): boolean {
    const trigger = workflow.actions.find((action) => action.type === 'trigger')
    const config = trigger?.config as { type?: string; filters?: Record<string, unknown> } | undefined
    const filters = config?.filters
    const events = filters?.events
    // A draft can store any value here.
    if (!Array.isArray(events) || !events.length || (Array.isArray(filters?.actions) && filters.actions.length)) {
        return false
    }
    const entries = events as { id?: unknown; type?: unknown }[]
    if (config?.type === 'internal-event') {
        return filters?.source === 'internal-events' && entries.every((event) => SUPPORT_EVENTS.has(String(event?.id)))
    }
    // The filter compiler matches the event name only on entries of type `events`, so another entry matches any event.
    return (
        config?.type === 'event' &&
        entries.every((event) => event?.type === 'events' && SUPPORT_EVENTS.has(String(event?.id)))
    )
}

/** The transactional categories the step's picker may offer: all of them where the save rule allows a transactional
 * step, only the one already selected when its type changed after it was chosen, and none otherwise. */
export function transactionalCategoryChoices(
    action: HogFlowAction,
    workflow: Pick<HogFlow, 'actions'>,
    categories: MessageCategory[]
): MessageCategory[] {
    const transactional = categories.filter((category) => category.category_type === 'transactional')
    const config = action.config as StepConfig
    if (
        !EMAIL_STEP_TYPES.includes(action.type) ||
        config.message_category_type === 'transactional' ||
        triggersOnlyOnSupportEvents(workflow)
    ) {
        return transactional
    }
    return transactional.filter((category) => category.id === config.message_category_id)
}

/** A copy is a new workflow, so its email steps lose the transactional type the original kept from before the rule. */
export function withMarketingEmailSteps(workflow: Pick<HogFlow, 'actions'>): HogFlow['actions'] {
    if (triggersOnlyOnSupportEvents(workflow)) {
        return workflow.actions
    }
    return workflow.actions.map((action) => {
        const config = action.config as StepConfig
        if (!EMAIL_STEP_TYPES.includes(action.type) || config.message_category_type !== 'transactional') {
            return action
        }
        return {
            ...action,
            config: { ...config, message_category_id: null, message_category_type: null },
        } as typeof action
    })
}
