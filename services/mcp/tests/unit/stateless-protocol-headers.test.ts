import { describe, expect, it } from 'vitest'

import {
    isModernRequest,
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    PROTOCOL_VERSION_HEADER,
    type ProtocolHeaders,
    readProtocolHeaders,
    validateModernRequest,
} from '@/lib/stateless-protocol'

const MODERN_VERSION = '2026-07-28'
const META_VERSION_KEY = 'io.modelcontextprotocol/protocolVersion'
const META_CLIENT_INFO_KEY = 'io.modelcontextprotocol/clientInfo'
const META_CLIENT_CAPABILITIES_KEY = 'io.modelcontextprotocol/clientCapabilities'

function headers(overrides: Partial<ProtocolHeaders> = {}): ProtocolHeaders {
    return { protocolVersion: null, method: null, name: null, ...overrides }
}

function modernMeta(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        [META_VERSION_KEY]: MODERN_VERSION,
        [META_CLIENT_INFO_KEY]: { name: 'unit-suite', version: '0.0.1' },
        [META_CLIENT_CAPABILITIES_KEY]: {},
        ...overrides,
    }
}

function modernMessage(
    method: string,
    params: Record<string, unknown> = {},
    meta: Record<string, unknown> = modernMeta()
): { method: string; params: Record<string, unknown> } {
    return { method, params: { ...params, _meta: meta } }
}

function matchingHeaders(message: { method: string; params: Record<string, unknown> }): ProtocolHeaders {
    const name = message.params.name ?? message.params.uri
    return headers({
        protocolVersion: MODERN_VERSION,
        method: message.method,
        name: typeof name === 'string' ? name : null,
    })
}

describe('stateless protocol operation headers', () => {
    it.each([
        ['modern _meta version', headers(), { protocolVersion: MODERN_VERSION }, true],
        ['legacy _meta version', headers(), { protocolVersion: '2025-03-26' }, true],
        ['garbage _meta version', headers(), { protocolVersion: 'not-a-version' }, true],
        ['modern header, no _meta', headers({ protocolVersion: MODERN_VERSION }), {}, true],
        ['legacy header, no _meta', headers({ protocolVersion: '2025-06-18' }), {}, false],
        ['no signals', headers(), {}, false],
    ])('isModernRequest detects %s as modern=%s', (_label, protocolHeaders, meta, expected) => {
        expect(isModernRequest(protocolHeaders, meta)).toBe(expected)
    })

    it('readProtocolHeaders reads header names case-insensitively', () => {
        const parsed = readProtocolHeaders(
            new Headers({ 'mcp-protocol-version': MODERN_VERSION, 'MCP-METHOD': 'tools/list', 'mcp-name': 'x' })
        )
        expect(parsed).toEqual({ protocolVersion: MODERN_VERSION, method: 'tools/list', name: 'x' })
    })

    it.each([
        ['tools/call with matching name', modernMessage('tools/call', { name: 'get_weather', arguments: {} })],
        ['prompts/get with matching name', modernMessage('prompts/get', { name: 'code_review' })],
        ['resources/read with matching uri', modernMessage('resources/read', { uri: 'file:///a/b.json' })],
        ['tools/list without Mcp-Name', modernMessage('tools/list')],
        ['notification without Mcp-Name', modernMessage('notifications/cancelled', { requestId: 1 })],
    ])('accepts a valid modern %s', (_label, message) => {
        expect(validateModernRequest(matchingHeaders(message), message)).toBeNull()
    })

    it('ignores an extraneous Mcp-Name on methods that do not require it', () => {
        const message = modernMessage('tools/list')
        expect(validateModernRequest({ ...matchingHeaders(message), name: 'stray' }, message)).toBeNull()
    })

    const call = modernMessage('tools/call', { name: 'get_weather', arguments: {} })
    it.each([
        [
            'missing MCP-Protocol-Version header',
            { ...matchingHeaders(call), protocolVersion: null },
            call,
            -32020,
            PROTOCOL_VERSION_HEADER,
        ],
        [
            'MCP-Protocol-Version header/_meta mismatch',
            { ...matchingHeaders(call), protocolVersion: '2025-06-18' },
            call,
            -32020,
            "'2025-06-18'",
        ],
        [
            'modern header with no _meta version',
            headers({ protocolVersion: MODERN_VERSION, method: 'tools/list' }),
            { method: 'tools/list', params: {} },
            -32020,
            '(missing)',
        ],
        ['missing Mcp-Method header', { ...matchingHeaders(call), method: null }, call, -32020, MCP_METHOD_HEADER],
        [
            'Mcp-Method header/body mismatch',
            { ...matchingHeaders(call), method: 'server/discover' },
            call,
            -32020,
            "'server/discover'",
        ],
        [
            'Mcp-Method case mismatch (values are case-sensitive)',
            { ...matchingHeaders(call), method: 'Tools/Call' },
            call,
            -32020,
            "'Tools/Call'",
        ],
        [
            'missing Mcp-Name header on tools/call',
            { ...matchingHeaders(call), name: null },
            call,
            -32020,
            MCP_NAME_HEADER,
        ],
        [
            'Mcp-Name header/body mismatch',
            { ...matchingHeaders(call), name: 'other_tool' },
            call,
            -32020,
            "'other_tool'",
        ],
        [
            'Mcp-Name mismatch against resources/read uri',
            headers({ protocolVersion: MODERN_VERSION, method: 'resources/read', name: 'file:///wrong' }),
            modernMessage('resources/read', { uri: 'file:///a/b.json' }),
            -32020,
            "'file:///wrong'",
        ],
        [
            'unsupported _meta version',
            matchingHeaders(call),
            modernMessage('tools/call', { name: 'get_weather' }, modernMeta({ [META_VERSION_KEY]: '2025-03-26' })),
            -32022,
            'Unsupported protocol version',
        ],
        [
            'missing clientInfo',
            matchingHeaders(call),
            modernMessage('tools/call', { name: 'get_weather' }, modernMeta({ [META_CLIENT_INFO_KEY]: undefined })),
            -32602,
            META_CLIENT_INFO_KEY,
        ],
        [
            'clientInfo without version',
            matchingHeaders(call),
            modernMessage('tools/call', { name: 'get_weather' }, modernMeta({ [META_CLIENT_INFO_KEY]: { name: 'x' } })),
            -32602,
            META_CLIENT_INFO_KEY,
        ],
        [
            'missing clientCapabilities',
            matchingHeaders(call),
            modernMessage(
                'tools/call',
                { name: 'get_weather' },
                modernMeta({ [META_CLIENT_CAPABILITIES_KEY]: undefined })
            ),
            -32602,
            META_CLIENT_CAPABILITIES_KEY,
        ],
    ])('rejects %s', (_label, protocolHeaders, message, expectedCode, messageSubstring) => {
        const error = validateModernRequest(protocolHeaders, message)
        expect(error?.code).toBe(expectedCode)
        expect(error?.message).toContain(messageSubstring)
    })

    it('reports the unsupported version (with retry data) before any header errors', () => {
        const message = modernMessage('tools/list', {}, modernMeta({ [META_VERSION_KEY]: '2025-03-26' }))
        const error = validateModernRequest(headers(), message)
        expect(error?.code).toBe(-32022)
        expect(error?.data).toEqual({ supported: [MODERN_VERSION], requested: '2025-03-26' })
    })
})
