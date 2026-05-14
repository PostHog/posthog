import { executeTool, resolveHandler } from './registry'
import { ToolContext } from './types'

const CTX: ToolContext = {
    sessionId: 's1',
    teamId: 7,
    applicationId: 'app-1',
    revisionId: 'rev-1',
    secrets: {},
}

describe('tool registry', () => {
    it('resolves meta.complete and returns the output', async () => {
        const result = await executeTool({ id: 'meta.complete', args: { output: { foo: 1 } } }, CTX)
        expect(result).toEqual({ ok: true, value: { foo: 1 } })
    })

    it('resolves meta.wait_for_input', async () => {
        const result = await executeTool({ id: 'meta.wait_for_input', args: { reason: 'paused' } }, CTX)
        expect(result).toEqual({ ok: true, value: { suspended: true, reason: 'paused' } })
    })

    it('rejects unknown tool ids', async () => {
        const result = await executeTool({ id: 'something.unknown', args: {} }, CTX)
        expect(result).toEqual({ ok: false, error: expect.stringContaining('unknown tool id') })
    })

    it('validates builtin args against the registry schema', async () => {
        const handler = resolveHandler('posthog.events.capture')
        expect(handler).not.toBeNull()
        const bad = await handler!.invoke({ id: 'posthog.events.capture', args: { event: 'signup' } }, CTX)
        expect(bad.ok).toBe(false)
    })

    it('runs a valid builtin call', async () => {
        const result = await executeTool(
            { id: 'posthog.events.capture', args: { event: 'signup', distinctId: 'u-1' } },
            CTX
        )
        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.value).toMatchObject({ captured: true, teamId: 7 })
        }
    })
})
