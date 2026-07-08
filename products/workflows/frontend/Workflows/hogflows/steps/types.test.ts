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

    // A cleared HogFlowDuration input emits just the unit (e.g. "d") and clobbering that with a
    // permissive schema lets users activate a wait step with no real timeout, so the workflow could
    // wait indefinitely. These cases lock in that only real durations pass.
    const delayAction = (delay_duration: string): Record<string, unknown> => ({
        id: 'delay_node',
        name: 'Delay',
        type: 'delay',
        description: '',
        config: { delay_duration },
    })

    const waitAction = (max_wait_duration: string): Record<string, unknown> => ({
        id: 'wait_node',
        name: 'Wait',
        type: 'wait_until_condition',
        description: '',
        config: { condition: { filters: {} }, max_wait_duration },
    })

    it.each([
        ['3d', true],
        ['10m', true],
        ['1m', true],
        ['1h', true],
        ['d', false],
        ['h', false],
        ['m', false],
        ['', false],
        ['NaNd', false],
        ['3', false],
        ['0m', false],
        ['0d', false],
        ['1.5h', false],
        ['0.5h', false],
        ['.5d', false],
        ['0.1m', false],
    ])('delay_duration %p → valid=%p', (duration, valid) => {
        expect(HogFlowActionSchema.safeParse(delayAction(duration)).success).toBe(valid)
    })

    it.each([
        ['5m', true],
        ['2h', true],
        ['1d', true],
        ['d', false],
        ['h', false],
        ['m', false],
        ['', false],
        ['NaNd', false],
        ['0m', false],
        ['0d', false],
        ['1.5h', false],
        ['0.5h', false],
    ])('max_wait_duration %p → valid=%p', (duration, valid) => {
        expect(HogFlowActionSchema.safeParse(waitAction(duration)).success).toBe(valid)
    })
})
