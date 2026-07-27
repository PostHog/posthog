import { describe, expect, it } from 'vitest'

import { HogFlowsCreateBody } from '@/generated/workflows/api'

// The MCP executor passes the zod-PARSED tool input to handlers, and a matched zod object branch
// strips keys it doesn't declare. The action config schema is a union with a free-form branch
// first, so parsing must preserve every config verbatim — the typed wait_until_condition branch
// is shape guidance only. These tests pin that invariant.
describe('workflows create schema — action config', () => {
    const triggerAction = {
        id: 'trigger_node',
        name: 'Trigger',
        type: 'trigger',
        config: {
            type: 'event',
            filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
        },
    }

    it('accepts a wait_until_condition action with events to wait for and preserves config verbatim', () => {
        const waitConfig = {
            condition: {
                filters: { properties: [{ key: 'plan', value: ['growth'], operator: 'exact', type: 'person' }] },
                name: 'If plan is growth',
            },
            events: [
                {
                    filters: { events: [{ id: 'purchase', name: 'purchase', type: 'events', order: 0 }] },
                    name: 'Purchase happened',
                },
            ],
            max_wait_duration: '30m',
            // Undeclared key: must survive parsing — proves the free-form union branch wins and
            // the typed branch never strips.
            some_future_key: 'must survive',
        }
        const result = HogFlowsCreateBody.safeParse({
            name: 'Wait until workflow',
            actions: [
                triggerAction,
                { id: 'wait_1', name: 'Wait for purchase', type: 'wait_until_condition', config: waitConfig },
            ],
        })

        expect(result.success).toBe(true)
        if (!result.success) {
            throw new Error(result.error.message)
        }
        expect(result.data.actions[1]?.config).toEqual(waitConfig)
    })

    it('accepts an events-only wait (no condition) and preserves config verbatim', () => {
        // The runtime supports waits with only events to wait for; 'condition' must not be
        // schema-required, or agents would be nudged into adding an empty condition to satisfy it.
        const waitConfig = {
            events: [
                {
                    filters: { events: [{ id: 'purchase', name: 'purchase', type: 'events', order: 0 }] },
                },
            ],
            max_wait_duration: '1h',
        }
        const result = HogFlowsCreateBody.safeParse({
            name: 'Events-only wait workflow',
            actions: [
                triggerAction,
                { id: 'wait_1', name: 'Wait for purchase', type: 'wait_until_condition', config: waitConfig },
            ],
        })

        expect(result.success).toBe(true)
        if (!result.success) {
            throw new Error(result.error.message)
        }
        expect(result.data.actions[1]?.config).toEqual(waitConfig)
    })

    it('accepts an empty condition and preserves it (runtime ignores it, relying on events/timeout)', () => {
        const waitConfig = {
            condition: { filters: {} },
            events: [
                {
                    filters: { events: [{ id: 'purchase', name: 'purchase', type: 'events', order: 0 }] },
                },
            ],
            max_wait_duration: '30m',
        }
        const result = HogFlowsCreateBody.safeParse({
            name: 'Empty condition wait workflow',
            actions: [
                triggerAction,
                { id: 'wait_1', name: 'Wait for purchase', type: 'wait_until_condition', config: waitConfig },
            ],
        })

        expect(result.success).toBe(true)
        if (!result.success) {
            throw new Error(result.error.message)
        }
        expect(result.data.actions[1]?.config).toEqual(waitConfig)
    })

    it('preserves other action type configs verbatim', () => {
        const functionConfig = {
            template_id: 'template-webhook',
            inputs: { url: { value: 'https://example.com' } },
        }
        const result = HogFlowsCreateBody.safeParse({
            name: 'Function workflow',
            actions: [triggerAction, { id: 'fn_1', name: 'Webhook', type: 'function', config: functionConfig }],
        })

        expect(result.success).toBe(true)
        if (!result.success) {
            throw new Error(result.error.message)
        }
        expect(result.data.actions[0]?.config).toEqual(triggerAction.config)
        expect(result.data.actions[1]?.config).toEqual(functionConfig)
    })
})
