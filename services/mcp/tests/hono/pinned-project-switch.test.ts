import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

// End-to-end guard for the pinned-connection project switch, driven through the
// real app: the resolver, the session-scoped cache, and the switch-project
// handler only agree if their wiring is intact, and every layer between them is
// mocked out in the unit tests.
describe('switch-project on a pinned connection', () => {
    const PINNED_PROJECT = '1'
    const SWITCHED_PROJECT = '2'

    const flagReads: string[] = []
    const flagWrites: string[] = []

    const flagHandlers = [
        http.get('*/api/projects/:projectId/feature_flags/', ({ params }) => {
            flagReads.push(String(params['projectId']))
            return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
        }),
        http.post('*/api/projects/:projectId/feature_flags/', ({ params }) => {
            flagWrites.push(String(params['projectId']))
            return HttpResponse.json({ id: 7, key: 'switch-project-probe' })
        }),
    ]

    const mswServer = setupServer(...flagHandlers, ...handlers, contextMillHandler)

    function createInMemoryRedis(): RedisLike & {
        ping(): Promise<string>
        incrby(key: string, n: number): Promise<number>
    } {
        const store = new Map<string, string>()
        return {
            get: async (key) => store.get(key) ?? null,
            set: async (key, value) => {
                store.set(key, String(value))
                return 'OK'
            },
            del: async (...keys) => {
                let removed = 0
                for (const key of keys) {
                    if (store.delete(key)) {
                        removed++
                    }
                }
                return removed
            },
            scan: async (cursor) => {
                const cur = String(cursor)
                return [cur === '0' ? 'next' : '0', cur === '0' ? Array.from(store.keys()) : []] as [string, string[]]
            },
            ...makeRedisRateLimitStubs(store),
            ping: async () => 'PONG',
        }
    }

    let app: ReturnType<typeof createApp>['app']

    beforeAll(async () => {
        process.env.TEST = '1'
        mswServer.listen({ onUnhandledRequest: 'bypass' })
        const created = createApp(createInMemoryRedis())
        app = created.app
        await created.warmup()
    })

    afterAll(() => {
        mswServer.close()
    })

    beforeEach(() => {
        flagReads.length = 0
        flagWrites.length = 0
    })

    let requestId = 0

    // Every request resends the same `x-posthog-project-id` pin, the way PostHog
    // Desktop and task sandboxes do.
    async function post(
        method: string,
        params: Record<string, unknown> | undefined,
        mcpSessionId?: string
    ): Promise<Response> {
        requestId += 1
        return app.request('/mcp', {
            method: 'POST',
            headers: {
                Authorization: 'Bearer phx_pinned_project_test_token',
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                'x-posthog-project-id': PINNED_PROJECT,
                ...(mcpSessionId ? { 'mcp-session-id': mcpSessionId } : {}),
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: `req-${requestId}`, method, params }),
        })
    }

    async function callTool(
        name: string,
        args: Record<string, unknown>,
        mcpSessionId: string
    ): Promise<{ isError?: boolean; content?: Array<{ text?: string }> }> {
        const response = await post('tools/call', { name, arguments: args }, mcpSessionId)
        expect(response.status).toBe(200)
        const body = (await response.json()) as {
            result?: { isError?: boolean; content?: Array<{ text?: string }> }
            error?: unknown
        }
        expect(body.error).toBeUndefined()
        return body.result ?? {}
    }

    it('sends later reads and writes to the switched project, not the resent pin', async () => {
        const initResponse = await post('initialize', {
            capabilities: {},
            clientInfo: { name: 'pinned-project-test', version: '0.0.1' },
        })
        const mcpSessionId = initResponse.headers.get('mcp-session-id')
        expect(mcpSessionId).toBeTruthy()

        const switchResult = await callTool('switch-project', { projectId: Number(SWITCHED_PROJECT) }, mcpSessionId!)
        expect(switchResult.isError).toBeFalsy()

        await callTool('feature-flag-get-all', {}, mcpSessionId!)
        await callTool('create-feature-flag', { key: 'switch-project-probe' }, mcpSessionId!)

        expect(flagReads).toEqual([SWITCHED_PROJECT])
        expect(flagWrites).toEqual([SWITCHED_PROJECT])
    })

    it('retargets the session when the connection changes its pin', async () => {
        // A pin the client genuinely changed is a new target, not a resend, so it
        // must win over the earlier switch — otherwise a reconnected client stays
        // stuck on wherever the previous session wandered.
        const initResponse = await post('initialize', {
            capabilities: {},
            clientInfo: { name: 'pinned-project-test', version: '0.0.1' },
        })
        const mcpSessionId = initResponse.headers.get('mcp-session-id')!

        await callTool('switch-project', { projectId: Number(SWITCHED_PROJECT) }, mcpSessionId)

        const response = await app.request('/mcp', {
            method: 'POST',
            headers: {
                Authorization: 'Bearer phx_pinned_project_test_token',
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                'x-posthog-project-id': '3',
                'mcp-session-id': mcpSessionId,
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                id: 'repin-1',
                method: 'tools/call',
                params: { name: 'feature-flag-get-all', arguments: {} },
            }),
        })
        expect(response.status).toBe(200)

        expect(flagReads).toEqual(['3'])
    })
})
