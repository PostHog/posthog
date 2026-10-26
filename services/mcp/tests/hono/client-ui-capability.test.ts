import { describe, expect, it } from 'vitest'

import { parseClientInfo } from '@/hono/request-utils'
import { STATELESS_PROTOCOL_VERSION } from '@/lib/stateless-protocol'

const UI_EXTENSION = { 'io.modelcontextprotocol/ui': { mimeTypes: ['text/html;profile=mcp-app'] } }

function initialize(capabilities?: unknown): string {
    return JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: { protocolVersion: '2025-06-18', clientInfo: { name: 'host', version: '1' }, capabilities },
    })
}

function statelessCall(capabilities?: unknown): string {
    return JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'tools/call',
        params: {
            name: 'posthog-agent-run',
            _meta: {
                'io.modelcontextprotocol/protocolVersion': STATELESS_PROTOCOL_VERSION,
                'io.modelcontextprotocol/clientInfo': { name: 'host', version: '1' },
                ...(capabilities ? { 'io.modelcontextprotocol/clientCapabilities': capabilities } : {}),
            },
        },
    })
}

describe('parseClientInfo UI app support', () => {
    it.each([
        ['initialize with the UI extension', initialize({ extensions: UI_EXTENSION }), true],
        ['initialize without the UI extension', initialize({ roots: {} }), false],
        ['initialize without capabilities', initialize(), undefined],
        ['a stateless request with the UI extension', statelessCall({ extensions: UI_EXTENSION }), true],
        ['a stateless request without the UI extension', statelessCall({ sampling: {} }), false],
        ['a stateless request without capabilities', statelessCall(), undefined],
    ])('reads %s', (_label, body, expected) => {
        expect(parseClientInfo(body).supportsUiApps).toBe(expected)
    })
})
