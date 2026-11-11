import { HogFlow } from './hogflows/types'
import { canMoveToBroadcasts } from './workflowBroadcastMoveLogic'

const step = (id: string, type: string, config: Record<string, any>): HogFlow['actions'][number] =>
    ({ id, type, name: id, description: '', created_at: 0, updated_at: 0, config }) as HogFlow['actions'][number]

const trigger = step('trigger_node', 'trigger', { type: 'batch', filters: {} })
const email = step('email_node', 'function_email', { template_id: 'template-email', inputs: {} })
const secondEmail = step('email_node_2', 'function_email', { template_id: 'template-email', inputs: {} })
const exit = step('exit_node', 'exit', { reason: 'Default exit' })

const oneEmailFlow = {
    id: 'flow',
    name: 'Flow',
    status: 'draft',
    exit_condition: 'exit_only_at_end',
    origin_product: null,
    draft: null,
    actions: [trigger, email, exit],
    edges: [
        { from: 'trigger_node', to: 'email_node', type: 'continue' },
        { from: 'email_node', to: 'exit_node', type: 'continue' },
    ],
} as unknown as HogFlow

describe('canMoveToBroadcasts', () => {
    it.each([
        ['a workflow that sends one email to a batch audience', {}, true],
        ['a broadcast already', { origin_product: 'broadcasts' }, false],
        ['a loop', { origin_product: 'loops' }, false],
        ['an archived workflow', { status: 'archived' }, false],
        ['a workflow with a staged draft', { draft: { name: 'Next' } }, false],
        ['a workflow that exits on a condition', { exit_condition: 'exit_on_conversion' }, false],
        [
            'a workflow with a second email',
            {
                actions: [trigger, email, secondEmail, exit],
                edges: [
                    { from: 'trigger_node', to: 'email_node', type: 'continue' },
                    { from: 'email_node', to: 'email_node_2', type: 'continue' },
                    { from: 'email_node_2', to: 'exit_node', type: 'continue' },
                ],
            },
            false,
        ],
        [
            'an event-triggered workflow',
            { actions: [step('trigger_node', 'trigger', { type: 'event', filters: {} }), email, exit] },
            false,
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(canMoveToBroadcasts({ ...oneEmailFlow, ...overrides } as HogFlow)).toBe(expected)
    })
})
