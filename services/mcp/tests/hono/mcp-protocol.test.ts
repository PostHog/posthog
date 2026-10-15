import Ajv from 'ajv'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'
import { ToolCatalog } from '@/hono/tool-catalog'
import { META_CLIENT_CAPABILITIES, META_CLIENT_INFO, META_PROTOCOL_VERSION } from '@/lib/stateless-protocol'
import {
    agentViewCancelArguments,
    agentViewReplyArguments,
    agentViewStatusArguments,
} from '@/tools/posthogAgent/operations'
import type { Context } from '@/tools/types'

import {
    defineAuthTests,
    defineCatalogFilterTests,
    defineExecModeTests,
    defineHttpRouteTests,
    defineJsonRpcEdgeCaseTests,
    defineMcpProtocolTests,
    defineResilienceTests,
    defineResourceCatalogTests,
    defineSessionLifecycleTests,
    defineSessionTrackingTests,
    defineStatelessProtocolTests,
    type ProtocolTestHarness,
} from '../integration/mcp-protocol-suite'
import { handlers, contextMillHandler } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mswServer = setupServer(...handlers, contextMillHandler)

function createInMemoryRedis(): RedisLike & {
    ping(): Promise<string>
    incrby(key: string, increment: number): Promise<number>
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
    process.env.MCP_APPS_BASE_URL = 'https://apps.test'
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    const created = createApp(createInMemoryRedis())
    app = created.app
    await created.warmup()
})

afterAll(() => {
    mswServer.close()
})

const fetchViaApp: typeof fetch = async (input, init) => {
    const url = input instanceof URL ? input : new URL(typeof input === 'string' ? input : input.url)
    return app.request(url.pathname + url.search, init ?? {})
}

const harness = (): ProtocolTestHarness => ({
    baseUrl: new URL('http://hono.test'),
    fetch: fetchViaApp,
    token: 'phx_integration_test_token',
    stateless: true,
    gracefulUnknown: true,
    publicRoutes: true,
})

defineMcpProtocolTests('Hono', harness)
defineResilienceTests('Hono', harness)
defineHttpRouteTests('Hono', harness)
defineAuthTests('Hono', harness)
defineJsonRpcEdgeCaseTests('Hono', harness)
defineSessionLifecycleTests('Hono', harness)
defineResourceCatalogTests('Hono', harness)
defineCatalogFilterTests('Hono', harness)
defineExecModeTests('Hono', harness)
defineSessionTrackingTests('Hono', harness)
defineStatelessProtocolTests('Hono', harness)

describe('/agent endpoint', () => {
    async function listTools(path: string): Promise<Array<{ name: string; inputSchema: object }>> {
        const res = await app.request(path, {
            method: 'POST',
            headers: {
                Authorization: 'Bearer phx_integration_test_token',
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                'x-posthog-mcp-mode': 'tools',
                'x-posthog-flag-overrides': JSON.stringify({ 'posthog-agent-mcp': true }),
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
        })
        const body = (await res.json()) as { result: { tools: Array<{ name: string; inputSchema: object }> } }
        return body.result.tools
    }

    async function listToolNames(path: string): Promise<string[]> {
        return (await listTools(path)).map((tool) => tool.name)
    }

    it('serves exactly the PostHog Agent tools, and /mcp does not serve them', async () => {
        const agentTools = await listToolNames('/agent')
        const mainTools = await listToolNames('/mcp')

        expect(agentTools.sort()).toEqual(
            ['posthog-agent-cancel', 'posthog-agent-reply', 'posthog-agent-run', 'posthog-agent-status'].sort()
        )
        expect(mainTools.length).toBeGreaterThan(10)
        expect(mainTools.filter((name) => name.startsWith('posthog-agent-'))).toEqual([])
    })

    // ChatGPT rejects a call from a UI app whose arguments do not match the schema in `tools/list`.
    const operation = { id: 'op-1', project: { id: 1, name: 'Test project' }, cursor: 'c1' }
    it.each([
        ['posthog-agent-status', agentViewStatusArguments(operation)],
        ['posthog-agent-reply', agentViewReplyArguments(operation, 'allow', 'req-1')],
        ['posthog-agent-cancel', agentViewCancelArguments(operation)],
    ])('the PostHog Agent view calls %s with arguments that match the listed schema', async (name, args) => {
        const tool = (await listTools('/agent')).find((t) => t.name === name)!
        const validate = new Ajv({ strict: false }).compile(tool.inputSchema)

        expect(validate(args), JSON.stringify(validate.errors)).toBe(true)
    })
})

describe('progress streaming', () => {
    const AGENT_TOOL = 'posthog-agent-status'
    const MAIN_TOOL = 'projects-get'
    const progressHandler = async (context: Context): Promise<string> => {
        context.reportProgress?.('Starting')
        context.reportProgress?.('Halfway')
        return `streamed=${context.reportProgress !== undefined}`
    }

    beforeEach(() => {
        const original = ToolCatalog.prototype.getToolByName
        vi.spyOn(ToolCatalog.prototype, 'getToolByName').mockImplementation(function (this: ToolCatalog, name) {
            const preBuilt = original.call(this, name)
            if (!preBuilt || (name !== AGENT_TOOL && name !== MAIN_TOOL)) {
                return preBuilt
            }
            return {
                ...preBuilt,
                build: () => ({ name, schema: z.object({}).passthrough(), handler: progressHandler }),
            }
        })
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    async function callTool(
        path: string,
        options: { progressToken?: string | number; accept?: string; stateless?: boolean; tool?: string }
    ): Promise<Response> {
        const tool = options.tool ?? AGENT_TOOL
        const meta: Record<string, unknown> = {}
        if (options.progressToken !== undefined) {
            meta.progressToken = options.progressToken
        }
        const headers: Record<string, string> = {
            Authorization: 'Bearer phx_integration_test_token',
            'Content-Type': 'application/json',
            Accept: options.accept ?? 'application/json, text/event-stream',
            'x-posthog-mcp-mode': 'tools',
            'x-posthog-flag-overrides': JSON.stringify({ 'posthog-agent-mcp': true }),
        }
        if (options.stateless) {
            meta[META_PROTOCOL_VERSION] = '2026-07-28'
            meta[META_CLIENT_INFO] = { name: 'progress-test-client', version: '1.0.0' }
            meta[META_CLIENT_CAPABILITIES] = {}
            headers['MCP-Protocol-Version'] = '2026-07-28'
            headers['Mcp-Method'] = 'tools/call'
            headers['Mcp-Name'] = tool
        }
        return app.request(path, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                jsonrpc: '2.0',
                id: 7,
                method: 'tools/call',
                params: { name: tool, arguments: {}, _meta: meta },
            }),
        })
    }

    function parseEvents(body: string): Array<{ event: string; data: Record<string, any> }> {
        return body
            .split('\n\n')
            .filter(Boolean)
            .map((block) => {
                const lines = block.split('\n')
                return {
                    event: lines.find((l) => l.startsWith('event: '))!.slice('event: '.length),
                    data: JSON.parse(lines.find((l) => l.startsWith('data: '))!.slice('data: '.length)),
                }
            })
    }

    it.each([
        ['legacy', false, 'tok-1'],
        ['stateless', true, 42],
    ])(
        'streams progress then the result on /agent for a %s tools/call with a progress token',
        async (_dialect, stateless, progressToken) => {
            const res = await callTool('/agent', { progressToken, stateless })

            expect(res.status).toBe(200)
            expect(res.headers.get('content-type')).toBe('text/event-stream')
            const events = parseEvents(await res.text())
            expect(events.map((e) => e.event)).toEqual(['message', 'message', 'message'])
            expect(events.slice(0, 2).map((e) => e.data)).toEqual([
                {
                    jsonrpc: '2.0',
                    method: 'notifications/progress',
                    params: { progressToken, progress: 1, message: 'Starting' },
                },
                {
                    jsonrpc: '2.0',
                    method: 'notifications/progress',
                    params: { progressToken, progress: 2, message: 'Halfway' },
                },
            ])
            expect(events[2]!.data).toMatchObject({
                jsonrpc: '2.0',
                id: 7,
                result: { content: expect.arrayContaining([{ type: 'text', text: 'streamed=true' }]) },
            })
            if (stateless) {
                expect(events[2]!.data.result.resultType).toBe('complete')
            }
        }
    )

    it.each([
        ['/agent without a progress token', '/agent', AGENT_TOOL, undefined, undefined],
        ['/agent without an event-stream Accept header', '/agent', AGENT_TOOL, 'tok-1', 'application/json'],
        ['/mcp with a progress token', '/mcp', MAIN_TOOL, 'tok-1', undefined],
    ])('answers with one JSON body on %s', async (_name, path, tool, progressToken, accept) => {
        const res = await callTool(path, { tool, progressToken, accept })

        expect(res.status).toBe(200)
        expect(res.headers.get('content-type')).toBe('application/json')
        expect(await res.json()).toMatchObject({
            jsonrpc: '2.0',
            id: 7,
            result: { content: expect.arrayContaining([{ type: 'text', text: 'streamed=false' }]) },
        })
    })
})
