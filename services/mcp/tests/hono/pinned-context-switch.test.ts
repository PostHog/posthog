import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const PINNED_PROJECT = '1'
const PINNED_ORG = '019d85ef-7e7d-0000-090c-f2f598b3949b'
const OTHER_PROJECT = '2'
const OTHER_ORG = '019d85ef-7e7d-0000-090c-000000000002'

const apiPaths: string[] = []

const mswServer = setupServer(
    http.get('*/api/projects/:projectId/', ({ params }) =>
        HttpResponse.json({
            id: Number(params.projectId),
            uuid: `0000000${String(params.projectId)}-0000-0000-0000-000000000000`,
            name: `Project ${String(params.projectId)}`,
            organization: params.projectId === OTHER_PROJECT ? OTHER_ORG : PINNED_ORG,
        })
    ),
    http.post('*/api/environments/:projectId/mcp_tools/execute_sql/', ({ request }) => {
        apiPaths.push(new URL(request.url).pathname)
        return HttpResponse.json({ success: true, content: 'ok' })
    }),
    http.get('*/api/organizations/:orgId/billing/subscription/', ({ request }) => {
        apiPaths.push(new URL(request.url).pathname)
        return HttpResponse.json({})
    }),
    ...handlers,
    contextMillHandler
)

function createInMemoryRedis(): RedisLike & { ping(): Promise<string> } {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async () => ['0', Array.from(store.keys())] as [string, string[]],
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

async function callTool(
    name: string,
    args: Record<string, unknown>,
    mcpSessionId: string | undefined
): Promise<{ isError?: boolean; text: string }> {
    const response = await app.request(`/mcp?project_id=${PINNED_PROJECT}`, {
        method: 'POST',
        headers: {
            Authorization: 'Bearer phx_pinned_context_test_token',
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'x-posthog-mcp-mode': 'tools',
            'x-posthog-flag-overrides': JSON.stringify({ 'organization-billing-api': true }),
            ...(mcpSessionId ? { 'mcp-session-id': mcpSessionId } : {}),
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
    })
    const raw = await response.text()
    const json = JSON.parse(raw.startsWith('{') ? raw : raw.slice(raw.indexOf('{'))) as {
        result?: { isError?: boolean; content?: Array<{ text?: string }> }
        error?: { message?: string }
    }
    if (!json.result) {
        throw new Error(`tools/call ${name} failed: ${json.error?.message ?? raw}`)
    }
    return { isError: json.result.isError, text: json.result.content?.[0]?.text ?? '' }
}

async function runQueryAndBilling(mcpSessionId: string | undefined): Promise<string[]> {
    apiPaths.length = 0
    expect((await callTool('execute-sql', { query: 'SELECT 1' }, mcpSessionId)).isError).toBeFalsy()
    expect((await callTool('billing-subscription-get', {}, mcpSessionId)).isError).toBeFalsy()
    return [...apiPaths]
}

const pathsFor = (projectId: string, orgId: string): string[] => [
    `/api/environments/${projectId}/mcp_tools/execute_sql/`,
    `/api/organizations/${orgId}/billing/subscription/`,
]

describe('pinned project with switch-project (Hono)', () => {
    beforeEach(() => {
        apiPaths.length = 0
    })

    it('runs query and billing tools against the switched project, and keeps other sessions on the pin', async () => {
        const switched = await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, 'session-a')
        expect(switched.isError).toBeFalsy()
        expect(switched.text).toContain(`Switched to project ${OTHER_PROJECT}`)

        // Each call resends the same pin, which must not revert the switch.
        expect(await runQueryAndBilling('session-a')).toEqual(pathsFor(OTHER_PROJECT, OTHER_ORG))

        // A second session on the same credential keeps its own pin.
        expect(await runQueryAndBilling('session-b')).toEqual(pathsFor(PINNED_PROJECT, PINNED_ORG))
        expect(await runQueryAndBilling('session-a')).toEqual(pathsFor(OTHER_PROJECT, OTHER_ORG))
    })

    it('refuses switch-project without an MCP session instead of reporting a switch the pin reverts', async () => {
        const switched = await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, undefined)
        expect(switched.isError).toBe(true)
        expect(switched.text).toContain('sends no MCP session id')

        expect(await runQueryAndBilling(undefined)).toEqual(pathsFor(PINNED_PROJECT, PINNED_ORG))
    })
})
