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
        ['30s', true],
        ['1.5h', true],
        ['0.5h', true],
        ['.5d', true],
        ['0.1m', true],
        ['d', false],
        ['h', false],
        ['m', false],
        ['s', false],
        ['', false],
        ['NaNd', false],
        ['3', false],
        ['3w', false],
        ['0m', false],
        ['0d', false],
        ['0.0h', false],
    ])('delay_duration %p → valid=%p', (duration, valid) => {
        expect(HogFlowActionSchema.safeParse(delayAction(duration)).success).toBe(valid)
    })

    // The API takes exactly one of the two delay modes. A config the editor calls valid but the API
    // rejects saves as a draft and then fails to activate, pointing at nothing visible on screen.
    const delayConfigAction = (config: Record<string, unknown>): Record<string, unknown> => ({
        id: 'delay_node',
        name: 'Delay',
        type: 'delay',
        description: '',
        config,
    })

    it.each([
        ['a duration alone', { delay_duration: '1d' }, true],
        ['a date alone', { delay_until: { expression: 'person.properties.expires_at' } }, true],
        ['a date with an offset', { delay_until: { expression: 'person.properties.x', offset: '-1d' } }, true],
        ['a date with a cap', { delay_until: { expression: 'person.properties.x' }, max_delay_duration: '7d' }, true],
        ['both modes', { delay_duration: '1d', delay_until: { expression: 'person.properties.x' } }, false],
        ['neither mode', {}, false],
        ['a date with no expression', { delay_until: { expression: '' } }, false],
        ['an offset in an unsupported unit', { delay_until: { expression: 'x', offset: '1w' } }, false],
        ['a cap that is not a duration', { delay_until: { expression: 'x' }, max_delay_duration: '7' }, false],
    ])('delay config with %s → valid=%p', (_label, config, valid) => {
        expect(HogFlowActionSchema.safeParse(delayConfigAction(config)).success).toBe(valid)
    })

    it.each([
        ['5m', true],
        ['2h', true],
        ['1d', true],
        ['30s', true],
        ['1.5h', true],
        ['d', false],
        ['h', false],
        ['m', false],
        ['', false],
        ['NaNd', false],
        ['0m', false],
        ['0d', false],
    ])('max_wait_duration %p → valid=%p', (duration, valid) => {
        expect(HogFlowActionSchema.safeParse(waitAction(duration)).success).toBe(valid)
    })

    // The message the user sees depends on which rule failed, and the order matters: an empty field must
    // read "Please enter a duration", not the technical format/min messages. delay_duration and
    // max_wait_duration share DURATION_STRING, so testing one covers both.
    it.each([
        ['', 'Please enter a duration'],
        ['m', 'Please enter a duration'],
        ['3', 'Duration must be a number followed by s, m, h, or d'],
        ['3w', 'Duration must be a number followed by s, m, h, or d'],
        ['0m', 'Duration must be greater than 0'],
    ])('delay_duration %p → message %p', (duration, message) => {
        const result = HogFlowActionSchema.safeParse(delayAction(duration))
        expect(result.success).toBe(false)
        if (!result.success) {
            const issue = result.error.issues.find((i) => i.path.at(-1) === 'delay_duration')
            expect(issue?.message).toBe(message)
        }
    })
})
