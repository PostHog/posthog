import type { HogFlow, HogFlowAction } from '../Workflows/hogflows/types'
import type { MessageCategory } from './optOutCategoriesLogic'
import { canPickTransactionalCategory } from './transactionalCategories'

const categories = [
    { id: 'cat-news', category_type: 'marketing' },
    { id: 'cat-billing', category_type: 'transactional' },
] as MessageCategory[]

const workflowOn = (entry: Record<string, unknown>): Pick<HogFlow, 'actions'> =>
    ({
        actions: [{ id: 'trigger', type: 'trigger', config: { type: 'internal-event', filters: { events: [entry] } } }],
    }) as unknown as Pick<HogFlow, 'actions'>

const step = (type: string, config: Record<string, unknown> = {}): HogFlowAction =>
    ({ id: 'step', type, config }) as unknown as HogFlowAction

describe('canPickTransactionalCategory', () => {
    test.each([
        ['an SMS step', step('function_sms'), { id: '$pageview', type: 'events' }, true],
        ['a new email step', step('function_email'), { id: '$pageview', type: 'events' }, false],
        ['a test sender email step', step('email_sandbox'), { id: '$pageview', type: 'events' }, false],
        [
            'an email step that is already transactional',
            step('function_email', { message_category_type: 'transactional' }),
            { id: '$pageview', type: 'events' },
            true,
        ],
        [
            'an email step whose category became transactional',
            step('function_email', { message_category_id: 'cat-billing', message_category_type: 'marketing' }),
            { id: '$pageview', type: 'events' },
            true,
        ],
        ['a support reply', step('function_email'), { id: '$conversation_message_sent', type: 'events' }, true],
        ['a support entry that matches any event', step('function_email'), { id: '$conversation_message_sent' }, false],
    ])('%s', (_, action, entry, expected) => {
        expect(canPickTransactionalCategory(action, workflowOn(entry), categories)).toBe(expected)
    })
})
