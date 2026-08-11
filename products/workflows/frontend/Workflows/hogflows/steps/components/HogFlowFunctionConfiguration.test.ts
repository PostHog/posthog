import { CyclotronJobInvocationGlobals } from '~/types'

import { buildSampleGlobals } from './HogFlowFunctionConfiguration'

describe('buildSampleGlobals', () => {
    const realSampleGlobals: CyclotronJobInvocationGlobals = {
        project: { id: 2, name: 'Real project', url: 'https://app.example.com/project/2' },
        source: { name: 'Send email', url: 'https://app.example.com/project/2/workflows/1' },
        event: {
            uuid: '0192f0e1-0000-0000-0000-000000000000',
            event: 'purchase_completed',
            elements_chain: '',
            distinct_id: 'real-distinct-id',
            properties: { plan_tier: 'enterprise' },
            timestamp: '2026-01-01T00:00:00Z',
            url: 'https://app.example.com/project/2/events/0192f0e1',
        },
        person: {
            id: '0192f0e1-1111-1111-1111-111111111111',
            properties: { company: 'Acme' },
            name: 'Real person',
            url: 'https://app.example.com/person/0192f0e1',
        },
        groups: {},
    }

    it.each([
        ['event', { event: true, person: true, groups: true, request: false, project: true, source: true }],
        ['batch', { event: true, person: true, groups: false, request: false, project: true, source: true }],
        ['webhook', { event: false, person: false, groups: false, request: true, project: true, source: true }],
    ])('exposes the right globals for a %s trigger', (triggerType, present) => {
        const globals = buildSampleGlobals(triggerType, undefined)
        Object.entries(present).forEach(([key, shouldExist]) => {
            expect(key in globals).toBe(shouldExist)
        })
    })

    // Batch runs have no external event, but the worker backfills event.distinct_id at dequeue, so the
    // editor must expose event.distinct_id for batch or {event.distinct_id} wrongly warns as unknown.
    it.each(['event', 'batch'])('exposes event.distinct_id for a %s trigger', (triggerType) => {
        expect(buildSampleGlobals(triggerType, undefined).event).toHaveProperty('distinct_id')
    })

    it('prefers the property names of the real sample event over placeholders', () => {
        const globals = buildSampleGlobals('event', undefined, realSampleGlobals)

        expect(globals.event.properties).toEqual({ plan_tier: 'enterprise' })
        expect(globals.event.event).toBe('purchase_completed')
        expect(globals.person.properties).toEqual({ company: 'Acme' })
    })

    // Mirrors createExampleEvent, which hogFlowEditorTestLogic supplies for every non-event trigger.
    const exampleSampleGlobals: CyclotronJobInvocationGlobals = {
        project: { id: 2, name: 'Default project', url: 'https://app.example.com/project/2' },
        source: { name: 'Unnamed', url: 'https://app.example.com/project/2/workflows/1' },
        event: {
            uuid: '0192f0e1-2222-2222-2222-222222222222',
            event: '$pageview',
            elements_chain: '',
            distinct_id: '0192f0e1-3333-3333-3333-333333333333',
            properties: {
                $current_url: 'https://app.example.com/project/2/workflows/1',
                $browser: 'Chrome',
                this_is_an_example_event: true,
            },
            timestamp: '2026-01-01T00:00:00Z',
            url: 'https://app.example.com/project/2/events/0192f0e1',
        },
        person: {
            id: '0192f0e1-4444-4444-4444-444444444444',
            properties: { email: 'example@posthog.com' },
            name: 'Example person',
            url: 'https://app.example.com/person/0192f0e1',
        },
        groups: {},
    }

    // Only event triggers query a real event; every other trigger gets a synthesized $pageview that
    // must not overwrite the event the worker really backfills for a batch run.
    it('ignores the synthesized example event for a batch trigger', () => {
        const globals = buildSampleGlobals('batch', undefined, exampleSampleGlobals)

        expect(globals.event.event).toBe('$batch_hog_flow_invocation')
        expect(globals.event.properties).toEqual({})
    })

    // createGlobalsFromResponse leaves person undefined for an event with no person, so an overlay
    // that spreads the sample would drop person out of the autocomplete for anonymous events.
    it('keeps the placeholder for a global the real sample leaves undefined', () => {
        const globals = buildSampleGlobals('event', undefined, { ...realSampleGlobals, person: undefined })

        expect(globals.person.properties).toHaveProperty('email')
    })

    it('keeps trigger-specific globals the real sample cannot supply', () => {
        const globals = buildSampleGlobals('webhook', undefined, realSampleGlobals)

        expect(globals.request).toHaveProperty('body')
        expect('event' in globals).toBe(false)
    })

    it.each([
        ['with a real sample', realSampleGlobals],
        ['without a real sample', null],
    ])('merges workflow variables %s', (_label, sample) => {
        const globals = buildSampleGlobals(
            'event',
            [
                { key: 'name', type: 'string' },
                { key: 'count', type: 'number' },
            ],
            sample
        )

        expect(globals.variables).toEqual({ name: 'example_value', count: 123 })
    })
})
