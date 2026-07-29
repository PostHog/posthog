import { serve } from '@hono/node-server'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mswServer = setupServer(...handlers, contextMillHandler)

const TOKEN = 'phx_integration_test_token'

function createInMemoryRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async () => ['0', []] as [string, string[]],
        ...makeRedisRateLimitStubs(),
    }
}

let app: ReturnType<typeof createApp>['app']
let listener: ReturnType<typeof serve>
let baseUrl: string

beforeAll(async () => {
    process.env.MCP_SIGNED_STATE_KEY = 'a'.repeat(32)
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    const created = createApp(createInMemoryRedis())
    app = created.app
    await created.warmup()
    await new Promise<void>((resolve) => {
        listener = serve({ fetch: created.app.fetch, port: 0 }, (info) => {
            baseUrl = `http://127.0.0.1:${info.port}`
            resolve()
        })
    })
}, 60_000)

afterAll(async () => {
    await new Promise<void>((resolve) => listener.close(() => resolve()))
    mswServer.close()
})

function initializeBody(clientName: string): string {
    return JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
            protocolVersion: '2025-11-25',
            capabilities: {},
            clientInfo: { name: clientName, version: '1.0.0' },
        },
    })
}

async function initialize(clientName: string): Promise<string> {
    const res = await app.request('/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            Authorization: `Bearer ${TOKEN}`,
        },
        body: initializeBody(clientName),
    })
    expect(res.status).toBe(200)
    return res.headers.get('Mcp-Session-Id')!
}

async function openStream(headers: Record<string, string>): Promise<Response> {
    return await app.request('/mcp', {
        method: 'GET',
        headers: { Accept: 'text/event-stream', Authorization: `Bearer ${TOKEN}`, ...headers },
    })
}

async function readFirstFrame(res: Response): Promise<string> {
    const reader = res.body!.getReader()
    try {
        const { value } = await reader.read()
        return new TextDecoder().decode(value ?? new Uint8Array())
    } finally {
        await reader.cancel()
    }
}

describe('standalone SSE stream on GET /mcp', () => {
    // Antigravity gives up on the whole connection when the standalone stream can't
    // be opened, so it has to get one; every other client tolerates the 405 and must
    // keep getting it, or they all start holding a long-lived connection open.
    it.each([
        ['antigravity-client', true],
        ['antigravity-client (via mcp-remote 0.1.37)', true],
        ['claude-code', false],
        ['cursor-vscode', false],
    ])('serves the stream for %s: %s', async (clientName, served) => {
        const res = await openStream({ 'Mcp-Session-Id': await initialize(clientName) })

        if (!served) {
            expect(res.status).toBe(405)
            expect(res.headers.get('Allow')).toBe('GET, POST')
            return
        }

        expect(res.status).toBe(200)
        expect(res.headers.get('Content-Type')).toBe('text/event-stream')
        expect(await readFirstFrame(res)).toBe(': ping\n\n')
    })

    it('serves the stream when only the user agent identifies the client', async () => {
        const res = await openStream({ 'User-Agent': 'Antigravity/2.0.243' })
        expect(res.status).toBe(200)
        await readFirstFrame(res)
    })

    it('still requires a bearer token', async () => {
        const res = await app.request('/mcp', { method: 'GET', headers: { Accept: 'text/event-stream' } })
        expect(res.status).toBe(401)
    })

    // Over a real listener, not `app.request`: the point of the first frame is that it
    // reaches the client immediately. A buffered or content-length'd response would
    // satisfy every assertion above and still leave the client waiting.
    it('flushes the first frame over the wire and tears down on client abort', async () => {
        const init = await fetch(`${baseUrl}/mcp`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                Authorization: `Bearer ${TOKEN}`,
            },
            body: initializeBody('antigravity-client'),
        })
        const sessionId = init.headers.get('mcp-session-id')!

        const abort = new AbortController()
        const stream = await fetch(`${baseUrl}/mcp`, {
            method: 'GET',
            headers: {
                Accept: 'text/event-stream',
                Authorization: `Bearer ${TOKEN}`,
                'mcp-session-id': sessionId,
            },
            signal: abort.signal,
        })
        expect(stream.status).toBe(200)
        expect(stream.headers.get('transfer-encoding')).toBe('chunked')

        const reader = stream.body!.getReader()
        const { value } = await reader.read()
        expect(new TextDecoder().decode(value!)).toBe(': ping\n\n')

        abort.abort()
        await expect(reader.read()).rejects.toThrow()
    })
})
