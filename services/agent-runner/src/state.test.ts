import { SessionStateSchema, deserializeState, emptySessionState, serializeState } from './state'

describe('state serializer', () => {
    it('returns an empty state when the buffer is null', () => {
        const state = deserializeState(null)
        expect(state).toEqual({
            messages: [],
            pendingInputs: [],
            initialInput: null,
            turnCount: 0,
        })
    })

    it('round-trips a populated state', () => {
        const initial = emptySessionState({ foo: 'bar' })
        initial.messages.push({ role: 'user', content: 'hello' })
        initial.pendingInputs.push({ at: '2026-05-14T00:00:00.000Z', content: 'ping' })
        initial.turnCount = 2

        const buf = serializeState(initial)
        const back = deserializeState(buf)
        expect(back).toEqual(initial)
    })

    it('rejects malformed payloads via schema validation', () => {
        const bad = Buffer.from(JSON.stringify({ messages: 'not-an-array' }), 'utf8')
        expect(() => deserializeState(bad)).toThrow()
        expect(SessionStateSchema.safeParse({ messages: 'nope' }).success).toBe(false)
    })
})
