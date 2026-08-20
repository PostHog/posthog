import { buildSampleGlobals, filterInputsSchemaForTrigger } from './HogFlowFunctionConfiguration'

describe('HogFlowFunctionConfiguration', () => {
    describe('buildSampleGlobals', () => {
        it.each([
            ['event', { event: true, person: true, groups: true, request: false }],
            ['batch', { event: true, person: true, groups: false, request: false }],
            ['webhook', { event: false, person: false, groups: false, request: true }],
            // Slack-triggered runs are person-less.
            ['slack-message', { event: true, person: false, groups: false, request: false }],
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

        // Locks the sample property names to what the Slack trigger emits, so hand-typed
        // expressions like {event.properties.text} autocomplete instead of warning as unknown.
        it('exposes the Slack message properties for a slack-message trigger', () => {
            const properties = buildSampleGlobals('slack-message', undefined).event.properties
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
            ['slack-message', ['prompt', 'reply_in_slack_thread']],
            ['event', ['prompt']],
            [undefined, ['prompt']],
        ])('for the AI task step on a %s trigger shows %j', (triggerType, expectedKeys) => {
            const filtered = filterInputsSchemaForTrigger('template-posthog-create-task', triggerType, aiTaskSchema)
            expect(filtered.map((s) => s.key)).toEqual(expectedKeys)
        })

        it('leaves other templates untouched', () => {
            expect(filterInputsSchemaForTrigger('template-email', 'event', aiTaskSchema)).toEqual(aiTaskSchema)
        })
    })
})
