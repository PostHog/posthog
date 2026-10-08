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
const MISSING_PROJECT = '404'

const apiPaths: string[] = []

const mswServer = setupServer(
    http.get('*/api/projects/:projectId/', ({ params }) =>
        params.projectId === MISSING_PROJECT
            ? HttpResponse.json({ detail: 'Not found.' }, { status: 404 })
            : HttpResponse.json({
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

type CallOptions = {
    // Each test uses its own token, so the shared token cache never carries state between tests.
    token?: string
    query?: string
    sessionId?: string
}

function requestHeaders({ token = 'phx_default', sessionId }: CallOptions): Record<string, string> {
    return {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        'x-posthog-mcp-mode': 'tools',
        'x-posthog-flag-overrides': JSON.stringify({ 'organization-billing-api': true }),
        ...(sessionId ? { 'mcp-session-id': sessionId } : {}),
    }
}

async function initialize(options: CallOptions): Promise<string> {
    const response = await app.request(`/mcp${options.query ?? ''}`, {
        method: 'POST',
        headers: requestHeaders(options),
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 0,
            method: 'initialize',
            params: {
                protocolVersion: '2025-06-18',
                capabilities: {},
                clientInfo: { name: 'pin-test', version: '0.0.0' },
            },
        }),
    })
    const sessionId = response.headers.get('mcp-session-id')
    if (!sessionId) {
        throw new Error(`initialize returned no session id: ${await response.text()}`)
    }
    return sessionId
}

async function callTool(
    name: string,
    args: Record<string, unknown>,
    { query = `?project_id=${PINNED_PROJECT}`, ...options }: CallOptions = {}
): Promise<{ isError?: boolean; text: string }> {
    const response = await app.request(`/mcp${query}`, {
        method: 'POST',
        headers: requestHeaders(options),
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

async function runQueryAndBilling(options: CallOptions = {}): Promise<string[]> {
    apiPaths.length = 0
    expect((await callTool('execute-sql', { query: 'SELECT 1' }, options)).isError).toBeFalsy()
    expect((await callTool('billing-subscription-get', {}, options)).isError).toBeFalsy()
    return [...apiPaths]
}

async function runBilling(options: CallOptions): Promise<{ isError?: boolean; paths: string[] }> {
    apiPaths.length = 0
    const result = await callTool('billing-subscription-get', {}, options)
    return { isError: result.isError, paths: [...apiPaths] }
}

const pathsFor = (projectId: string, orgId: string): string[] => [
    `/api/environments/${projectId}/mcp_tools/execute_sql/`,
    `/api/organizations/${orgId}/billing/subscription/`,
]
const billingPathFor = (orgId: string): string[] => [`/api/organizations/${orgId}/billing/subscription/`]

// An unpinned, sessionless switch writes the shared token cache, as another session on the credential would.
async function cacheOtherProjectOnToken(token: string): Promise<void> {
    const switched = await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, { token, query: '' })
    expect(switched.isError).toBeFalsy()
    expect(await runQueryAndBilling({ token, query: '' })).toEqual(pathsFor(OTHER_PROJECT, OTHER_ORG))
}

describe('pinned project with switch-project (Hono)', () => {
    beforeEach(() => {
        apiPaths.length = 0
    })

    it('runs query and billing tools against the switched project, and keeps other sessions on the pin', async () => {
        const token = 'phx_switch'
        const switched = await callTool(
            'switch-project',
            { projectId: Number(OTHER_PROJECT) },
            { token, sessionId: 'session-a' }
        )
        expect(switched.isError).toBeFalsy()
        expect(switched.text).toContain(`Switched to project ${OTHER_PROJECT}`)

        // Each call resends the same pin, which must not revert the switch.
        expect(await runQueryAndBilling({ token, sessionId: 'session-a' })).toEqual(pathsFor(OTHER_PROJECT, OTHER_ORG))

        // A second session on the same credential keeps its own pin.
        expect(await runQueryAndBilling({ token, sessionId: 'session-b' })).toEqual(
            pathsFor(PINNED_PROJECT, PINNED_ORG)
        )
        expect(await runQueryAndBilling({ token, sessionId: 'session-a' })).toEqual(pathsFor(OTHER_PROJECT, OTHER_ORG))
    })

    it('refuses switch-project without an MCP session instead of reporting a switch the pin reverts', async () => {
        const token = 'phx_sessionless'
        const switched = await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, { token })
        expect(switched.isError).toBe(true)
        expect(switched.text).toContain('sends no MCP session id')

        expect(await runQueryAndBilling({ token })).toEqual(pathsFor(PINNED_PROJECT, PINNED_ORG))
    })

    it.each([
        ['project', `?project_id=${PINNED_PROJECT}`],
        ['organization', `?organization_id=${PINNED_ORG}`],
    ])('keeps a %s pin sent only on initialize for later requests in the session', async (kind, pinQuery) => {
        const token = `phx_init_${kind}`
        await cacheOtherProjectOnToken(token)

        const sessionId = await initialize({ token, query: pinQuery })

        const later = { token, sessionId, query: '' }
        if (kind === 'project') {
            expect(await runQueryAndBilling(later)).toEqual(pathsFor(PINNED_PROJECT, PINNED_ORG))
        } else {
            expect(await runBilling(later)).toEqual({ isError: undefined, paths: billingPathFor(PINNED_ORG) })
        }

        // The saved pin belongs to the credential: another token that reuses the session id keeps its own state.
        const otherToken = `phx_init_${kind}_other`
        await cacheOtherProjectOnToken(otherToken)
        expect(await runBilling({ token: otherToken, sessionId, query: '' })).toEqual({
            isError: undefined,
            paths: billingPathFor(OTHER_ORG),
        })
    })

    it("reports missing context instead of using another session's org when the pinned project lookup fails", async () => {
        const token = 'phx_missing_project'
        await cacheOtherProjectOnToken(token)

        const result = await runBilling({ token, query: `?project_id=${MISSING_PROJECT}` })

        expect(result.isError).toBe(true)
        expect(result.paths).toEqual([])
    })

    it("lets a sessionless project pin switch only to the project's own organization", async () => {
        const token = 'phx_switch_org'
        const ownOrg = await callTool('switch-organization', { orgId: PINNED_ORG }, { token })
        expect(ownOrg.isError).toBeFalsy()
        expect(await runBilling({ token })).toEqual({ isError: undefined, paths: billingPathFor(PINNED_ORG) })

        const otherOrg = await callTool('switch-organization', { orgId: OTHER_ORG }, { token })
        expect(otherOrg.isError).toBe(true)
        expect(otherOrg.text).toContain('sends no MCP session id')
        expect(await runBilling({ token })).toEqual({ isError: undefined, paths: billingPathFor(PINNED_ORG) })
    })
})
