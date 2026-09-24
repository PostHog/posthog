import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveClientIp } from '@/hono/client-ip'
import {
    EDGE_CLIENT_IP_HEADERS,
    MCP_CLIENT_IP_HEADERS,
    signClientIp,
    signedClientIpHeaders,
    verifySignedClientIp,
} from '@/lib/client-ip-signature'
import { honoRequestHeaders } from '@/proxy'

const KEY = 'managed-proxy-test-key'
const OLD_KEY = 'managed-proxy-old-key'
const NOW = 1_800_000_000
const CLIENT_IP = '203.0.113.7'
// The same vector as MANAGED_PROXY_KNOWN_ANSWER_SIGNATURE in posthog/test/test_middleware.py, so
// the TypeScript signer and the Django verifier cannot drift apart.
const KNOWN_ANSWER_SIGNATURE = 'f825f520f1c3a2ef243b6a055a528b8ce94a3b4b9110bb6f3c2b568191e7b717'

async function edgeHeaders(ip: string, key: string, timestamp: number = NOW): Promise<Record<string, string>> {
    return signedClientIpHeaders(EDGE_CLIENT_IP_HEADERS, [key], ip, timestamp)
}

describe('client IP signatures', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('signs in the format Django verifies', async () => {
        expect(await signClientIp(KEY, CLIENT_IP, String(NOW))).toBe(KNOWN_ANSWER_SIGNATURE)
    })

    it.each([
        ['the known answer', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [KEY], 'valid'],
        ['uppercase hex', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE.toUpperCase(), [KEY], 'valid'],
        ['an older key in the list', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [OLD_KEY, KEY], 'valid'],
        ['the oldest timestamp', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [KEY], 'valid', NOW + 60],
        ['the newest timestamp', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [KEY], 'valid', NOW - 5],
        [
            'an expired timestamp',
            CLIENT_IP,
            String(NOW),
            KNOWN_ANSWER_SIGNATURE,
            [KEY],
            'timestamp_out_of_window',
            NOW + 61,
        ],
        [
            'a future timestamp',
            CLIENT_IP,
            String(NOW),
            KNOWN_ANSWER_SIGNATURE,
            [KEY],
            'timestamp_out_of_window',
            NOW - 6,
        ],
        ['an unknown key', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [OLD_KEY], 'bad_signature'],
        ['a signature for another IP', '192.0.2.1', String(NOW), KNOWN_ANSWER_SIGNATURE, [KEY], 'bad_signature'],
        ['a signature that is not hex', CLIENT_IP, String(NOW), 'z'.repeat(64), [KEY], 'bad_signature'],
        ['a fractional timestamp', CLIENT_IP, `${NOW}.0`, KNOWN_ANSWER_SIGNATURE, [KEY], 'invalid_input'],
        ['an oversized timestamp', CLIENT_IP, '1'.repeat(5000), KNOWN_ANSWER_SIGNATURE, [KEY], 'invalid_input'],
        ['no signature', CLIENT_IP, String(NOW), null, [KEY], 'invalid_input'],
        ['no key', CLIENT_IP, String(NOW), KNOWN_ANSWER_SIGNATURE, [], 'not_configured'],
    ] as const)('verifies %s', async (_label, ip, timestamp, signature, keys, expected, now = NOW) => {
        expect(await verifySignedClientIp(ip, timestamp, signature, [...keys], now)).toBe(expected)
    })

    describe('resolveClientIp', () => {
        it.each([
            [
                'the IP the Worker signed',
                async () => ({ ...(await edgeHeaders(CLIENT_IP, KEY)), 'x-forwarded-for': '198.51.100.10' }),
                [KEY],
                { ip: CLIENT_IP, source: 'edge', edgeOutcome: 'valid' },
            ],
            [
                'no IP, not the Cloudflare forwarded-for, when the edge signature fails',
                async () => ({ ...(await edgeHeaders(CLIENT_IP, OLD_KEY)), 'x-forwarded-for': '198.51.100.10' }),
                [KEY],
                { ip: undefined, source: 'none', edgeOutcome: 'bad_signature' },
            ],
            [
                'no IP when the runtime holds no edge key',
                async () => edgeHeaders(CLIENT_IP, KEY),
                [],
                { ip: undefined, source: 'none', edgeOutcome: 'not_configured' },
            ],
            [
                'the forwarded-for entry the ingress wrote, not one the client sent',
                async () => ({ 'x-forwarded-for': '192.0.2.99, 198.51.100.10' }),
                [KEY],
                { ip: '198.51.100.10', source: 'forwarded', edgeOutcome: 'absent' },
            ],
            [
                'no IP for a malformed forwarded-for entry',
                async () => ({ 'x-forwarded-for': 'not-an-ip' }),
                [KEY],
                { ip: undefined, source: 'none', edgeOutcome: 'absent' },
            ],
        ] as const)('returns %s', async (_label, buildHeaders, keys, expected) => {
            expect(await resolveClientIp(new Headers(await buildHeaders()), [...keys], NOW)).toEqual(expected)
        })
    })

    describe('honoRequestHeaders', () => {
        it('replaces client-sent IP headers with a signature for the region it proxies to', async () => {
            vi.stubEnv('MCP_EDGE_CLIENT_IP_SIGNING_KEYS_EU', `${KEY},${OLD_KEY}`)
            vi.stubEnv('MCP_EDGE_CLIENT_IP_SIGNING_KEYS_US', 'us-only-key')
            const incoming = new Headers({
                'cf-connecting-ip': CLIENT_IP,
                authorization: 'Bearer phx_test',
                [EDGE_CLIENT_IP_HEADERS.ip]: '192.0.2.1',
                [EDGE_CLIENT_IP_HEADERS.signature]: 'forged',
                [MCP_CLIENT_IP_HEADERS.ip]: '192.0.2.1',
            })

            const headers = await honoRequestHeaders(incoming, 'eu')

            expect(headers.get(EDGE_CLIENT_IP_HEADERS.ip)).toBe(CLIENT_IP)
            expect(headers.get(MCP_CLIENT_IP_HEADERS.ip)).toBeNull()
            expect(headers.get('authorization')).toBe('Bearer phx_test')
            expect(await resolveClientIp(headers, [KEY])).toMatchObject({ ip: CLIENT_IP, source: 'edge' })
            expect(await resolveClientIp(headers, ['us-only-key'])).toMatchObject({ source: 'none' })
        })

        it('sends no IP headers when the region has no key', async () => {
            vi.stubEnv('MCP_EDGE_CLIENT_IP_SIGNING_KEYS_US', '')
            const incoming = new Headers({
                'cf-connecting-ip': CLIENT_IP,
                [EDGE_CLIENT_IP_HEADERS.ip]: '192.0.2.1',
            })

            const headers = await honoRequestHeaders(incoming, 'us')

            expect([...headers.keys()].filter((name) => name.startsWith('x-posthog-'))).toEqual([])
        })
    })
})
