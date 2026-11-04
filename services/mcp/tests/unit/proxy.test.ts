import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveProxyRegion } from '@/proxy'

const OK = { status: 200, body: { distinct_id: 'user-1' } }
const UNAUTHORIZED = { status: 401, body: { detail: 'Invalid access token.' } }
const MISSING_SCOPE = {
    status: 403,
    body: {
        type: 'authentication_error',
        code: 'permission_denied',
        detail: "API key missing required scope 'user:read'",
    },
}

type ProbeResponse = { status: number; body: unknown }

function stubRegions(us: ProbeResponse, eu: ProbeResponse): void {
    vi.stubGlobal(
        'fetch',
        vi.fn(async (input: string | URL | Request) => {
            const url = input instanceof Request ? input.url : String(input)
            const { status, body } = url.includes('eu.posthog.com') ? eu : us
            return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
        })
    )
}

describe('resolveProxyRegion', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        vi.restoreAllMocks()
    })

    it.each([
        ['a US token', OK, UNAUTHORIZED, 'us'],
        ['an EU token', UNAUTHORIZED, OK, 'eu'],
        ['a US token without user:read', MISSING_SCOPE, UNAUTHORIZED, 'us'],
        ['an EU token without user:read', UNAUTHORIZED, MISSING_SCOPE, 'eu'],
    ])('routes %s to its home region', async (_, us, eu, expected) => {
        stubRegions(us, eu)
        const kv = { get: vi.fn(async () => null), put: vi.fn(async () => undefined) }

        expect(await resolveProxyRegion('pha_test', 'hash', kv as unknown as KVNamespace)).toBe(expected)
        expect(kv.put).toHaveBeenCalledWith('hash:region', expected, expect.anything())
    })

    it.each([
        [
            'the cache read fails',
            { get: vi.fn(async () => Promise.reject(new Error('kv down'))), put: vi.fn(async () => undefined) },
        ],
        [
            'the cache write fails',
            { get: vi.fn(async () => null), put: vi.fn(async () => Promise.reject(new Error('kv down'))) },
        ],
    ])('still routes an EU token without user:read to EU when %s', async (_, kv) => {
        stubRegions(UNAUTHORIZED, MISSING_SCOPE)
        vi.spyOn(console, 'error').mockImplementation(() => {})

        expect(await resolveProxyRegion('pha_test', 'hash', kv as unknown as KVNamespace)).toBe('eu')
    })
})
