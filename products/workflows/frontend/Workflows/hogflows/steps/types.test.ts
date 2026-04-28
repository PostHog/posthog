import { HogFlowActionSchema } from './types'

describe('HogFlowActionSchema', () => {
    it.each([
        [
            'trigger',
            {
                id: 'trigger_node',
                name: 'Trigger',
                type: 'trigger',
                description: '',
                config: {
                    type: 'event',
                    filters: {
                        events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    },
                },
            },
        ],
        [
            'exit',
            {
                id: 'exit_node',
                name: 'Exit',
                type: 'exit',
                description: '',
                config: { reason: 'Default exit' },
            },
        ],
        [
            'function',
            {
                id: 'action_function_abc123',
                name: 'Send webhook',
                type: 'function',
                description: '',
                config: { template_id: 'template-webhook', inputs: {} },
            },
        ],
    ])('validates %s action without created_at/updated_at', (_label, action) => {
        const result = HogFlowActionSchema.safeParse(action)
        expect(result.success).toBe(true)
    })
})
