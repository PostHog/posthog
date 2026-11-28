import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'
import type { MessageCategory } from './optOutCategoriesLogic'
import { transactionalCategoryChoices, withMarketingEmailSteps } from './transactionalCategories'

const categories = [
    { id: 'cat-news', name: 'News', category_type: 'marketing' },
    { id: 'cat-billing', name: 'Billing', category_type: 'transactional' },
    { id: 'cat-security', name: 'Security', category_type: 'transactional' },
] as MessageCategory[]

const eventTrigger = (...events: Record<string, unknown>[]): Record<string, unknown> => ({
    type: 'event',
    filters: { source: 'events', events },
})
const internalEventTrigger = (...ids: string[]): Record<string, unknown> => ({
    type: 'internal-event',
    filters: { source: 'internal-events', events: ids.map((id) => ({ id, name: id, type: 'events' })) },
})
const pageview = eventTrigger({ id: '$pageview', name: '$pageview', type: 'events' })
const ticketCreated = eventTrigger({ id: '$conversation_ticket_created', type: 'events' })

const step = (type: string, config: Record<string, unknown> = {}): HogFlowAction =>
    ({ id: 'email_1', name: 'Email', type, config: { template_id: 'template-email', ...config } }) as HogFlowAction

const workflow = (trigger: Record<string, unknown>, action: HogFlowAction): Pick<HogFlow, 'actions'> =>
    ({
        actions: [{ id: 'trigger_node', type: 'trigger', config: trigger }, action, { id: 'exit_node', type: 'exit' }],
    }) as Pick<HogFlow, 'actions'>

describe('transactional categories', () => {
    test.each([
        ['an SMS step', pageview, step('function_sms'), ['cat-billing', 'cat-security']],
        ['a new email step', pageview, step('function_email'), []],
        ['a test sender email step', pageview, step('email_sandbox'), []],
        [
            'an email step that is already transactional',
            pageview,
            step('function_email', { message_category_type: 'transactional' }),
            ['cat-billing', 'cat-security'],
        ],
        [
            'an email step whose category became transactional',
            pageview,
            step('function_email', { message_category_id: 'cat-billing', message_category_type: 'marketing' }),
            ['cat-billing'],
        ],
        [
            'a support reply',
            internalEventTrigger('$conversation_message_sent'),
            step('function_email'),
            ['cat-billing', 'cat-security'],
        ],
        ['a ticket update', ticketCreated, step('function_email'), ['cat-billing', 'cat-security']],
        [
            'an event named like support',
            eventTrigger({ id: '$conversation_spring_sale', type: 'events' }),
            step('function_email'),
            [],
        ],
        [
            'a support entry that matches any event',
            eventTrigger({ id: '$conversation_ticket_created' }),
            step('function_email'),
            [],
        ],
        [
            'a support event next to another event',
            eventTrigger({ id: '$conversation_ticket_created', type: 'events' }, { id: '$pageview', type: 'events' }),
            step('function_email'),
            [],
        ],
        [
            'a trigger saved with malformed events',
            { type: 'event', filters: { events: 1 } },
            step('function_email'),
            [],
        ],
    ])('the picker of %s offers its transactional categories', (_, trigger, action, expected) => {
        expect(
            transactionalCategoryChoices(action, workflow(trigger, action), categories).map((category) => category.id)
        ).toEqual(expected)
    })

    test.each([
        ['an ordinary workflow', pageview, undefined],
        ['a support workflow', ticketCreated, 'transactional'],
    ])('a copy of %s keeps a transactional email step as %s', (_, trigger, expected) => {
        const original = workflow(
            trigger,
            step('function_email', { message_category_id: 'cat-billing', message_category_type: 'transactional' })
        )

        const copied = withMarketingEmailSteps(original)[1].config as { message_category_type?: string }

        expect(copied.message_category_type).toBe(expected)
    })
})
