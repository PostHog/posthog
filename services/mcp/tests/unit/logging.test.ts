import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RequestLogger, withLogging } from '@/lib/logging'

function lastEmittedRecord(spy: ReturnType<typeof vi.spyOn>): Record<string, unknown> {
    expect(spy).toHaveBeenCalled()
    const lastCall = spy.mock.calls.at(-1)!
    expect(lastCall[0]).toBe('[MCP]')
    return JSON.parse(lastCall[1] as string) as Record<string, unknown>
}

describe('RequestLogger', () => {
    let infoSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
        infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    })

    afterEach(() => {
        infoSpy.mockRestore()
    })

    it('uses the provided requestId verbatim', () => {
        const log = new RequestLogger('fixed-id')
        log.emit(200)
        expect(lastEmittedRecord(infoSpy).requestId).toBe('fixed-id')
    })

    it('generates an 8-char requestId when none is provided', () => {
        const log = new RequestLogger()
        log.emit(200)
        const record = lastEmittedRecord(infoSpy)
        expect(record.requestId).toMatch(/^[0-9a-f]{8}$/)
    })

    it('accumulates extended fields and emits status + durationMs', () => {
        const log = new RequestLogger('r1')
        log.extend({ foo: 'bar' })
        log.extend({ baz: 1 })
        log.emit(204)
        const record = lastEmittedRecord(infoSpy)
        expect(record).toMatchObject({ requestId: 'r1', foo: 'bar', baz: 1, status: 204 })
        expect(typeof record.durationMs).toBe('number')
        expect(record.durationMs as number).toBeGreaterThanOrEqual(0)
    })

    it('extend overwrites prior values for the same key', () => {
        const log = new RequestLogger('r1')
        log.extend({ key: 'first' })
        log.extend({ key: 'second' })
        log.emit(200)
        expect(lastEmittedRecord(infoSpy).key).toBe('second')
    })
})

describe('withLogging', () => {
    let infoSpy: ReturnType<typeof vi.spyOn>
    const ctx = {} as ExecutionContext<unknown>
    const env = {} as Env

    beforeEach(() => {
        infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    })

    afterEach(() => {
        infoSpy.mockRestore()
    })

    it('redacts sensitive headers but preserves the rest verbatim', async () => {
        const handler = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp', {
            headers: {
                authorization: 'Bearer secret',
                cookie: 'session=abc',
                'x-api-key': 'topsecret',
                'x-custom': 'visible',
            },
        })

        await wrapped(request, env, ctx)

        const record = lastEmittedRecord(infoSpy)
        const headers = record.headers as Record<string, string>
        expect(headers.authorization).toBe('[REDACTED]')
        expect(headers.cookie).toBe('[REDACTED]')
        expect(headers['x-api-key']).toBe('[REDACTED]')
        expect(headers['x-custom']).toBe('visible')
    })

    it('captures method, pathname, search, and request mcpSessionId', async () => {
        const handler = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp?foo=1', {
            method: 'POST',
            headers: { 'mcp-session-id': 'sess-existing' },
        })

        await wrapped(request, env, ctx)

        expect(lastEmittedRecord(infoSpy)).toMatchObject({
            method: 'POST',
            pathname: '/mcp',
            search: '?foo=1',
            mcpSessionId: 'sess-existing',
            status: 200,
        })
    })

    it('promotes a server-minted session id when the request had none (initialize)', async () => {
        const handler = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 200,
                headers: { 'mcp-session-id': 'sess-newly-minted' },
            })
        )
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp', { method: 'POST' })

        await wrapped(request, env, ctx)

        expect(lastEmittedRecord(infoSpy).mcpSessionId).toBe('sess-newly-minted')
    })

    it('keeps the request session id when the response echoes the same id', async () => {
        const handler = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 200,
                headers: { 'mcp-session-id': 'sess-existing' },
            })
        )
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp', {
            method: 'POST',
            headers: { 'mcp-session-id': 'sess-existing' },
        })

        await wrapped(request, env, ctx)

        expect(lastEmittedRecord(infoSpy).mcpSessionId).toBe('sess-existing')
    })

    it('emits status 500 and rethrows when the handler throws', async () => {
        const boom = new Error('boom')
        const handler = vi.fn().mockRejectedValue(boom)
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp', { method: 'POST' })

        await expect(wrapped(request, env, ctx)).rejects.toBe(boom)

        expect(lastEmittedRecord(infoSpy)).toMatchObject({ status: 500, error: 'boom' })
    })

    it('stringifies non-Error throws in the error field', async () => {
        const handler = vi.fn().mockRejectedValue('plain string failure')
        const wrapped = withLogging(handler)
        const request = new Request('https://example.com/mcp', { method: 'POST' })

        await expect(wrapped(request, env, ctx)).rejects.toBe('plain string failure')

        expect(lastEmittedRecord(infoSpy).error).toBe('plain string failure')
    })
})
