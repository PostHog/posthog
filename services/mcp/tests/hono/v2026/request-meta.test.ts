import { describe, expect, it } from 'vitest'

import { JSON_RPC_ERROR, V2026ProtocolError } from '@/hono/v2026/errors'
import { parseV2026Meta } from '@/hono/v2026/request-meta'

const V = '2026-07-28'

function makeRequest(headers: Record<string, string>): Request {
    return new Request('http://localhost/mcp', { method: 'POST', headers })
}

function validBody(method: string, paramsOverride?: Record<string, unknown>): Record<string, unknown> {
    const params: Record<string, unknown> = {
        ...paramsOverride,
        _meta: {
            'io.modelcontextprotocol/protocolVersion': V,
            'io.modelcontextprotocol/clientInfo': { name: 'claude-code', version: '2.1.149' },
            'io.modelcontextprotocol/clientCapabilities': { elicitation: {} },
        },
    }
    return { jsonrpc: '2.0', id: 1, method, params }
}

describe('parseV2026Meta', () => {
    it('parses a fully-formed tools/call request', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
            'mcp-name': 'org-update',
        })
        const meta = parseV2026Meta(req, validBody('tools/call', { name: 'org-update' }))
        expect(meta.protocolVersion).toBe(V)
        expect(meta.method).toBe('tools/call')
        expect(meta.name).toBe('org-update')
        expect(meta.clientInfo.name).toBe('claude-code')
        expect(meta.clientCapabilities.elicitation).toEqual({})
    })

    it('parses an optional logLevel from _meta', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        const body = validBody('tools/call')
        ;(body.params as Record<string, unknown>)['_meta'] = {
            ...((body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>),
            'io.modelcontextprotocol/logLevel': 'info',
        }
        const meta = parseV2026Meta(req, body)
        expect(meta.logLevel).toBe('info')
    })

    it('rejects an invalid logLevel value', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        const body = validBody('tools/call')
        ;(body.params as Record<string, unknown>)['_meta'] = {
            ...((body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>),
            'io.modelcontextprotocol/logLevel': 'ludicrous',
        }
        try {
            parseV2026Meta(req, body)
            throw new Error('expected to throw')
        } catch (err) {
            expect(err).toBeInstanceOf(V2026ProtocolError)
            expect((err as V2026ProtocolError).code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
        }
    })

    it('rejects missing protocol version header', () => {
        const req = makeRequest({ 'mcp-method': 'tools/call' })
        try {
            parseV2026Meta(req, validBody('tools/call'))
            throw new Error('expected to throw')
        } catch (err) {
            expect((err as V2026ProtocolError).code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
            expect((err as V2026ProtocolError).httpStatus).toBe(400)
        }
    })

    it('rejects an unsupported protocol version', () => {
        const req = makeRequest({
            'mcp-protocol-version': '1999-01-01',
            'mcp-method': 'tools/call',
        })
        try {
            parseV2026Meta(req, validBody('tools/call'))
            throw new Error('expected to throw')
        } catch (err) {
            const e = err as V2026ProtocolError
            expect(e.code).toBe(JSON_RPC_ERROR.UNSUPPORTED_PROTOCOL_VERSION)
            expect(e.data?.requested).toBe('1999-01-01')
            expect(e.data?.supported).toEqual([V])
        }
    })

    it('rejects missing method header', () => {
        const req = makeRequest({ 'mcp-protocol-version': V })
        try {
            parseV2026Meta(req, validBody('tools/call'))
            throw new Error('expected to throw')
        } catch (err) {
            expect((err as V2026ProtocolError).code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
        }
    })

    it('rejects header/body method mismatch', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        try {
            parseV2026Meta(req, validBody('tools/list'))
            throw new Error('expected to throw')
        } catch (err) {
            const e = err as V2026ProtocolError
            expect(e.code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
            expect(e.message).toMatch(/does not match/)
        }
    })

    it('rejects header/body protocol-version mismatch', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        const body = validBody('tools/call')
        ;(body.params as Record<string, unknown>)['_meta'] = {
            ...((body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>),
            'io.modelcontextprotocol/protocolVersion': '2099-01-01',
        }
        try {
            parseV2026Meta(req, body)
            throw new Error('expected to throw')
        } catch (err) {
            expect((err as V2026ProtocolError).code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
        }
    })

    it('rejects missing _meta', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        try {
            parseV2026Meta(req, { jsonrpc: '2.0', id: 1, method: 'tools/call', params: {} })
            throw new Error('expected to throw')
        } catch (err) {
            const e = err as V2026ProtocolError
            expect(e.code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
            expect(e.message).toMatch(/_meta/)
        }
    })

    it('rejects missing clientInfo', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        const body = validBody('tools/call')
        const meta = (body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>
        delete meta['io.modelcontextprotocol/clientInfo']
        try {
            parseV2026Meta(req, body)
            throw new Error('expected to throw')
        } catch (err) {
            const e = err as V2026ProtocolError
            expect(e.code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
            expect(e.message).toMatch(/clientInfo/)
        }
    })

    it('rejects missing clientCapabilities', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/call',
        })
        const body = validBody('tools/call')
        const meta = (body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>
        delete meta['io.modelcontextprotocol/clientCapabilities']
        try {
            parseV2026Meta(req, body)
            throw new Error('expected to throw')
        } catch (err) {
            const e = err as V2026ProtocolError
            expect(e.code).toBe(JSON_RPC_ERROR.INVALID_PARAMS)
            expect(e.message).toMatch(/clientCapabilities/)
        }
    })

    it('accepts an empty capabilities object', () => {
        const req = makeRequest({
            'mcp-protocol-version': V,
            'mcp-method': 'tools/list',
        })
        const body = validBody('tools/list')
        const meta = (body.params as Record<string, unknown>)['_meta'] as Record<string, unknown>
        meta['io.modelcontextprotocol/clientCapabilities'] = {}
        const parsed = parseV2026Meta(req, body)
        expect(parsed.clientCapabilities).toEqual({})
    })

    it('case-insensitively reads header values', () => {
        // The HTTP spec is case-insensitive on header names; Request normalizes
        // them. Sanity check the helpers don't accidentally require lowercase.
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: {
                'MCP-Protocol-Version': V,
                'Mcp-Method': 'tools/call',
            },
        })
        const meta = parseV2026Meta(req, validBody('tools/call'))
        expect(meta.protocolVersion).toBe(V)
    })
})
