import { HttpGatewayClient } from './gateway-client'
import type { HttpFetcher } from './http-client'

// Minimal fetch stub: queue of {status, body} responses returned in
// order. The tests assert on the *request* via `calls` and on the *response*
// via the return value.
interface FakeResponse {
    status: number
    body: unknown
}

interface CapturedCall {
    url: string
    method: string
    authorization?: string
}

function installFetch(queue: FakeResponse[]): { http: HttpFetcher; calls: CapturedCall[]; restore: () => void } {
    const calls: CapturedCall[] = []
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            const url = typeof input === 'string' ? input : input.toString()
            const headers = init?.headers as Record<string, string> | undefined
            calls.push({
                url,
                method: init?.method ?? 'GET',
                authorization: headers?.['Authorization'] ?? headers?.['authorization'],
            })
            const next = queue.shift()
            if (!next) {
                throw new Error('fake fetch: queue empty')
            }
            const body = typeof next.body === 'string' ? next.body : JSON.stringify(next.body)
            return new Response(body, { status: next.status, headers: { 'Content-Type': 'application/json' } })
        },
    }
    return { http, calls, restore: () => {} }
}

describe('HttpGatewayClient.getUsage', () => {
    it('returns the parsed body on 200', async () => {
        const { http, calls, restore } = installFetch([
            {
                status: 200,
                body: {
                    request_id: 'agent:s1:1',
                    team_id: 1,
                    cost_usd: '0.000043',
                    input_tokens: 13,
                    output_tokens: 1,
                    settled_at: '2026-05-29T17:08:15Z',
                },
            },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw.local/v1', http })
            const usage = await c.getUsage('agent:s1:1', { phc: 'phc_abc' })
            expect(usage?.cost_usd).toBe('0.000043')
            expect(usage?.team_id).toBe(1)
            expect(calls).toHaveLength(1)
            expect(calls[0].url).toBe('http://gw.local/v1/usage/agent:s1:1')
            expect(calls[0].authorization).toBe('Bearer phc_abc')
        } finally {
            restore()
        }
    })

    it('does NOT URL-encode the request_id (path-param routers reject %3A)', async () => {
        // Regression for the chi/Go encoding bug: encoded colons return 404
        // on the gateway side because chi.URLParam returns the raw escaped
        // segment.
        const { http, calls, restore } = installFetch([
            { status: 200, body: { request_id: 'x', team_id: 0, cost_usd: '0', settled_at: '' } },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            await c.getUsage('agent:s1:1', { phc: 'phc_x' })
            expect(calls[0].url).toContain(':') // literal colons in the URL
            expect(calls[0].url).not.toContain('%3A')
        } finally {
            restore()
        }
    })

    it('retries on 404 with backoff and eventually returns the body', async () => {
        const { http, calls, restore } = installFetch([
            { status: 404, body: { error: 'not found' } },
            { status: 404, body: { error: 'not found' } },
            { status: 200, body: { request_id: 'x', team_id: 0, cost_usd: '0.001', settled_at: '' } },
        ])
        try {
            const c = new HttpGatewayClient({
                baseUrl: 'http://gw/v1',
                maxAttempts: 4,
                initialBackoffMs: 1,
                http,
            })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage?.cost_usd).toBe('0.001')
            expect(calls).toHaveLength(3)
        } finally {
            restore()
        }
    })

    it('returns null after max 404 attempts without throwing', async () => {
        const { http, calls, restore } = installFetch([
            { status: 404, body: '' },
            { status: 404, body: '' },
        ])
        try {
            const c = new HttpGatewayClient({
                baseUrl: 'http://gw/v1',
                maxAttempts: 2,
                initialBackoffMs: 1,
                http,
            })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage).toBeNull()
            expect(calls).toHaveLength(2)
        } finally {
            restore()
        }
    })

    it('returns null on non-404 errors without throwing', async () => {
        const { http, restore } = installFetch([{ status: 500, body: { error: 'boom' } }])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', maxAttempts: 1, http })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage).toBeNull()
        } finally {
            restore()
        }
    })
})

describe('HttpGatewayClient.getWalletBalance', () => {
    it('returns the parsed body on 200', async () => {
        const { http, calls, restore } = installFetch([
            {
                status: 200,
                body: {
                    team_id: 1,
                    available_usd: '99.999957',
                    pending_usd: '0',
                    currency: 'USD',
                },
            },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            const bal = await c.getWalletBalance({ phc: 'phc_z' })
            expect(bal.available_usd).toBe('99.999957')
            expect(bal.currency).toBe('USD')
            expect(calls[0].url).toBe('http://gw/v1/wallet/balance')
            expect(calls[0].authorization).toBe('Bearer phc_z')
        } finally {
            restore()
        }
    })

    it('throws on non-200', async () => {
        const { http, restore } = installFetch([{ status: 503, body: { error: 'down' } }])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            await expect(c.getWalletBalance({ phc: 'phc' })).rejects.toThrow(/wallet balance fetch failed/)
        } finally {
            restore()
        }
    })
})
