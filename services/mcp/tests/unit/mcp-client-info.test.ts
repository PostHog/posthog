import { describe, expect, it } from 'vitest'

import { extractClientInfoFromBody } from '@/lib/mcp-client-info'

function initializeMessage(
    clientInfo: { name?: string; version?: string } = { name: 'claude-code', version: '1.0.0' },
    protocolVersion = '2025-03-26'
): object {
    return {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
            protocolVersion,
            clientInfo,
            capabilities: {},
        },
    }
}

function postRequest(body: unknown): Request {
    return new Request('https://mcp.example.com/mcp', {
        method: 'POST',
        body: typeof body === 'string' ? body : JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
    })
}

describe('extractClientInfoFromBody', () => {
    it('extracts clientInfo + protocolVersion from a single initialize message', async () => {
        const info = await extractClientInfoFromBody(postRequest(initializeMessage()))
        expect(info).toEqual({
            clientName: 'claude-code',
            clientVersion: '1.0.0',
            protocolVersion: '2025-03-26',
        })
    })

    it('extracts clientInfo from a JSON-RPC batch', async () => {
        const batch = [
            { jsonrpc: '2.0', method: 'notifications/initialized' },
            initializeMessage({ name: 'Cursor', version: '0.42.1' }, '2025-03-26'),
        ]
        const info = await extractClientInfoFromBody(postRequest(batch))
        expect(info.clientName).toBe('Cursor')
        expect(info.clientVersion).toBe('0.42.1')
    })

    it('returns empty object when the body has no initialize message', async () => {
        const info = await extractClientInfoFromBody(postRequest({ jsonrpc: '2.0', method: 'tools/list', id: 2 }))
        expect(info).toEqual({})
    })

    it('returns empty object for GET requests (SSE endpoint)', async () => {
        const req = new Request('https://mcp.example.com/sse', { method: 'GET' })
        const info = await extractClientInfoFromBody(req)
        expect(info).toEqual({})
    })

    it('returns empty object for malformed JSON', async () => {
        const info = await extractClientInfoFromBody(postRequest('not-json'))
        expect(info).toEqual({})
    })

    it('does not consume the original request body', async () => {
        const req = postRequest(initializeMessage())
        await extractClientInfoFromBody(req)
        // The downstream MCP transport must still be able to read the body.
        const body = await req.text()
        expect(body).toContain('"method":"initialize"')
    })

    it('sanitizes clientName/version values', async () => {
        // sanitizeHeaderValue strips control characters and caps length — we
        // just smoke-test that a value with embedded newlines comes out clean.
        const info = await extractClientInfoFromBody(
            postRequest(initializeMessage({ name: 'claude-code\nX-Injected: evil', version: '1.0' }))
        )
        expect(info.clientName).not.toContain('\n')
    })
})
