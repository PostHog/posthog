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
        it.each([
            ['event', { type: 'event' }, { event: true, person: true, groups: true, request: false }],
            ['batch', { type: 'batch' }, { event: true, person: true, groups: false, request: false }],
            ['webhook', { type: 'webhook' }, { event: false, person: false, groups: false, request: true }],
            // Slack-triggered runs are person-less.
            ['slack message', slackTrigger, { event: true, person: false, groups: false, request: false }],
            // GitHub-triggered runs are person-less too.
            ['github event', githubTrigger, { event: true, person: false, groups: false, request: false }],
        ])('exposes the right globals for a %s trigger', (_name, trigger, present) => {
            const globals = buildSampleGlobals(trigger, undefined)
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
