import { getBuiltin, isBuiltinId, listBuiltins } from '..'

describe('builtins registry', () => {
    it('lists all registered builtins', () => {
        const ids = listBuiltins().map((b) => b.id)
        expect(ids).toEqual(
            expect.arrayContaining(['posthog.events.capture', 'posthog.feature_flags.evaluate', 'http.fetch'])
        )
    })

    it('looks builtins up by id', () => {
        const spec = getBuiltin('posthog.events.capture')
        expect(spec).not.toBeNull()
        expect(spec?.description).toMatch(/capture/i)
    })

    it('returns null for unknown ids', () => {
        expect(getBuiltin('nope.does_not_exist')).toBeNull()
        expect(isBuiltinId('nope.does_not_exist')).toBe(false)
    })

    it('validates args via the spec schema', () => {
        const spec = getBuiltin('posthog.events.capture')!
        expect(spec.args.safeParse({ event: 'signup', distinctId: 'user-1' }).success).toBe(true)
        expect(spec.args.safeParse({ event: 'signup' }).success).toBe(false)
    })
})
