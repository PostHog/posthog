import { buildSampleGlobals } from './HogFlowFunctionConfiguration'

describe('buildSampleGlobals', () => {
    it.each([
        ['event', { event: true, person: true, groups: true, request: false }],
        ['batch', { event: true, person: true, groups: false, request: false }],
        ['webhook', { event: false, person: false, groups: false, request: true }],
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

    it('maps workflow variables to typed placeholders', () => {
        const globals = buildSampleGlobals(undefined, [
            { key: 'name', type: 'string' },
            { key: 'count', type: 'number' },
        ])
        expect(globals.variables).toEqual({ name: 'example_value', count: 123 })
    })
})
