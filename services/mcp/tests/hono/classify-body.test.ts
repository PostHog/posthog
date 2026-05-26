import { describe, expect, it } from 'vitest'

import { classifyBody } from '@/hono/streamable-handler'

function makeRequest(body: string | undefined): Request {
    const init: RequestInit = { method: 'POST', headers: { 'Content-Type': 'application/json' } }
    if (body !== undefined) {
        init.body = body
    }
    return new Request('http://localhost/mcp', init)
}

describe('classifyBody', () => {
    it('classifies a JSONRPC request as `request` and preserves the body', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', id: '1', method: 'tools/call', params: {} }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
        // The dispatcher re-parses this; the rebuilt body must still be readable.
        if (result.kind === 'request') {
            const text = await result.req.text()
            expect(JSON.parse(text)).toMatchObject({ method: 'tools/call' })
        }
    })

    it('classifies a JSONRPC result-response as `response`', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', id: 'e1', result: { action: 'accept' } }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('response')
        if (result.kind === 'response') {
            expect(result.id).toBe('e1')
            expect(result.payload).toEqual({ action: 'accept' })
        }
    })

    it('classifies a JSONRPC error-response as `response` and wraps the error envelope', async () => {
        const req = makeRequest(
            JSON.stringify({ jsonrpc: '2.0', id: 42, error: { code: -32601, message: 'not found' } })
        )
        const result = await classifyBody(req)
        expect(result.kind).toBe('response')
        if (result.kind === 'response') {
            expect(result.id).toBe(42)
            expect(result.payload).toEqual({ error: { code: -32601, message: 'not found' } })
        }
    })

    it('preserves numeric ids as numbers (not coerced to strings)', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', id: 99, result: {} }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('response')
        if (result.kind === 'response') {
            expect(result.id).toBe(99)
            expect(typeof result.id).toBe('number')
        }
    })

    it('falls through as `request` for batches (server-initiated batch responses are not supported)', async () => {
        const req = makeRequest(JSON.stringify([{ jsonrpc: '2.0', id: '1', method: 'ping' }]))
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for a notification (no id)', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for malformed JSON (dispatcher will produce a parse error)', async () => {
        const req = makeRequest('{not-json')
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for an empty body', async () => {
        const req = makeRequest('')
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for ambiguous payload missing both result and error', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', id: '1' }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for a response shape with no id (cannot be routed)', async () => {
        const req = makeRequest(JSON.stringify({ jsonrpc: '2.0', result: {} }))
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })

    it('falls through as `request` for null body parsed value', async () => {
        const req = makeRequest('null')
        const result = await classifyBody(req)
        expect(result.kind).toBe('request')
    })
})
