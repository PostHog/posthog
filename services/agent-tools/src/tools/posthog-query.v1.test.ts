import { setPosthogInternalClient } from '../posthog-client'
import { makeCapturingCtx } from '../test-helpers'
import { posthogQueryV1 } from './posthog-query.v1'

describe('posthog.query.v1', () => {
    it('delegates to the internal client and logs', async () => {
        const calls: Array<{ team_id: number; query: string }> = []
        setPosthogInternalClient({
            async runHogql(input) {
                calls.push(input)
                return { rows: [{ x: 1 }], columns: ['x'] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
        const { ctx, logs } = makeCapturingCtx()
        const out = await posthogQueryV1.run({ query: 'select 1 as x' }, ctx)
        expect(out).toEqual({ rows: [{ x: 1 }], columns: ['x'] })
        expect(calls).toEqual([{ team_id: 1, query: 'select 1 as x' }])
        expect(logs[0].msg).toBe('hogql.executed')
    })

    it('validates args via schema', () => {
        expect(() => posthogQueryV1.schema.args.parse({ query: '' })).toThrow()
        expect(posthogQueryV1.schema.args.parse({ query: 'select 1' })).toEqual({ query: 'select 1' })
    })
})
