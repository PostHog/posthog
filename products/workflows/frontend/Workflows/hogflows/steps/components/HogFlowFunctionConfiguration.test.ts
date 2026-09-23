import { CyclotronJobInvocationGlobals } from '~/types'

import { buildSampleGlobals, filterInputsSchemaForTrigger } from './HogFlowFunctionConfiguration'

// The stored shape a Slack message workflow carries. The trigger type alone no longer identifies
// it, so every case below passes the whole config.
const slackTrigger = {
    type: 'internal-event',
    filters: { source: 'internal-events', events: [{ id: '$slack_message_received', type: 'events' }] },
}

const githubTrigger = {
    type: 'internal-event',
    filters: { source: 'internal-events', events: [{ id: '$github_event_received', type: 'events' }] },
}

describe('HogFlowFunctionConfiguration', () => {
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
        it('prefers the property names of the real sample event over placeholders', () => {
            const globals = buildSampleGlobals({ type: 'event' }, undefined, realSampleGlobals)

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
            const globals = buildSampleGlobals({ type: 'batch' }, undefined, exampleSampleGlobals)

            expect(globals.event.event).toBe('$batch_hog_flow_invocation')
            expect(globals.event.properties).toEqual({})
        })

        // createGlobalsFromResponse leaves person undefined for an event with no person, so an overlay
        // that spreads the sample would drop person out of the autocomplete for anonymous events.
        it('keeps the placeholder for a global the real sample leaves undefined', () => {
            const globals = buildSampleGlobals({ type: 'event' }, undefined, {
                ...realSampleGlobals,
                person: undefined,
            })

            expect(globals.person.properties).toHaveProperty('email')
        })

        it('keeps trigger-specific globals the real sample cannot supply', () => {
            const globals = buildSampleGlobals({ type: 'webhook' }, undefined, realSampleGlobals)

            expect(globals.request).toHaveProperty('body')
            expect('event' in globals).toBe(false)
        })

        it.each([
            ['with a real sample', realSampleGlobals],
            ['without a real sample', null],
        ])('merges workflow variables %s', (_label, sample) => {
            const globals = buildSampleGlobals(
                { type: 'event' },
                [
                    { key: 'name', type: 'string' },
                    { key: 'count', type: 'number' },
                ],
                sample
            )

            expect(globals.variables).toEqual({ name: 'example_value', count: 123 })
        })
        it.each([
            ['event', { type: 'event' }, { event: true, person: true, groups: true, request: false }],
            ['batch', { type: 'batch' }, { event: true, person: true, groups: false, request: false }],
            ['webhook', { type: 'webhook' }, { event: false, person: false, groups: false, request: true }],
            // Slack-triggered runs are person-less.
            ['slack message', slackTrigger, { event: true, person: false, groups: false, request: false }],
            // GitHub-triggered runs are person-less too.
            ['github event', githubTrigger, { event: true, person: false, groups: false, request: false }],
        ])('exposes the right globals for a %s trigger', (_name, trigger, present) => {
            const globals = buildSampleGlobals(trigger, undefined, exampleSampleGlobals)
            expect(globals).toHaveProperty('project')
            expect(globals).toHaveProperty('source')
            Object.entries(present).forEach(([key, shouldExist]) => {
                expect(key in globals).toBe(shouldExist)
            })
        })

        // Batch runs have no external event, but the worker backfills event.distinct_id at dequeue, so the
        // editor must expose event.distinct_id for batch or {event.distinct_id} wrongly warns as unknown.
        it.each(['event', 'batch'])('exposes event.distinct_id for a %s trigger', (triggerType) => {
            expect(buildSampleGlobals({ type: triggerType }, undefined).event).toHaveProperty('distinct_id')
        })

        // Locks the sample property names to what the Slack trigger emits, so hand-typed
        // expressions like {event.properties.text} autocomplete instead of warning as unknown.
        it('exposes the Slack message properties for a Slack message trigger', () => {
            const properties = buildSampleGlobals(slackTrigger, undefined).event.properties
            expect(properties).toMatchObject({
                channel: expect.any(String),
                text: expect.any(String),
                ts: expect.any(String),
                user: expect.any(String),
                slack_team_id: expect.any(String),
                integration_id: expect.any(Number),
            })
            expect('thread_ts' in properties).toBe(true)
        })

        // Locks the sample property names to what the GitHub trigger emits, so hand-typed
        // expressions like {event.properties.actor_access} autocomplete instead of warning as unknown.
        it('exposes the GitHub event properties for a GitHub trigger', () => {
            const properties = buildSampleGlobals(githubTrigger, undefined).event.properties
            expect(properties).toMatchObject({
                event_type: expect.any(String),
                repository: expect.any(String),
                sender: expect.any(String),
                actor_access: expect.any(String),
                author_association: expect.any(String),
                title: expect.any(String),
                body: expect.any(String),
                integration_id: expect.any(Number),
            })
            expect('bot_sender' in properties).toBe(true)
            expect('review_state' in properties).toBe(true)
        })

        it('maps workflow variables to typed placeholders', () => {
            const globals = buildSampleGlobals(undefined, [
                { key: 'name', type: 'string' },
                { key: 'count', type: 'number' },
            ])
            expect(globals.variables).toEqual({ name: 'example_value', count: 123 })
        })
    })

    describe('filterInputsSchemaForTrigger', () => {
        const aiTaskSchema = [{ key: 'prompt' }, { key: 'reply_in_slack_thread' }]

        it.each([
            ['slack message', slackTrigger, ['prompt', 'reply_in_slack_thread']],
            ['event', { type: 'event' }, ['prompt']],
            ['undefined', undefined, ['prompt']],
            // An internal-event trigger for some other event is not a Slack trigger.
            [
                'other internal event',
                { type: 'internal-event', filters: { source: 'internal-events', events: [{ id: '$other' }] } },
                ['prompt'],
            ],
            // A stored trigger from before the rename must not resolve as a Slack trigger.
            ['legacy slack-message', { type: 'slack-message', filters: {} }, ['prompt']],
        ])('for the AI task step on a %s trigger shows %j', (_name, trigger, expectedKeys) => {
            const filtered = filterInputsSchemaForTrigger('template-posthog-create-task', trigger, aiTaskSchema)
            expect(filtered.map((s) => s.key)).toEqual(expectedKeys)
        })

        it('leaves other templates untouched', () => {
            expect(filterInputsSchemaForTrigger('template-email', { type: 'event' }, aiTaskSchema)).toEqual(
                aiTaskSchema
            )
        })
    })
})
