import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createHash } from 'node:crypto'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import { RedisCache, type RedisLike } from '@/hono/cache/RedisCache'
import { hash } from '@/lib/utils'
import type { SessionScopedState, State } from '@/tools/types'

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
let redis: ReturnType<typeof createInMemoryRedis>

beforeAll(async () => {
    process.env.TEST = '1'
    process.env.MCP_APPS_BASE_URL = 'https://apps.test'
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    redis = createInMemoryRedis()
    const created = createApp(redis)
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

type ToolCallResponse = {
    status: number
    result?: { isError?: boolean; content?: Array<{ text?: string }> }
    error?: { code?: number; message?: string; data?: { reason?: string } }
}

async function postToolCall(
    name: string,
    args: Record<string, unknown>,
    { query = `?project_id=${PINNED_PROJECT}`, ...options }: CallOptions = {}
): Promise<ToolCallResponse> {
    const response = await app.request(`/mcp${query}`, {
        method: 'POST',
        headers: requestHeaders(options),
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
    })
    const raw = await response.text()
    const json = JSON.parse(raw.startsWith('{') ? raw : raw.slice(raw.indexOf('{'))) as Omit<ToolCallResponse, 'status'>
    return { status: response.status, ...json }
}

async function callTool(
    name: string,
    args: Record<string, unknown>,
    options: CallOptions = {}
): Promise<{ isError?: boolean; text: string }> {
    const { result, error } = await postToolCall(name, args, options)
    if (!result) {
        throw new Error(`tools/call ${name} failed: ${error?.message ?? 'no result'}`)
    }
    return { isError: result.isError, text: result.content?.[0]?.text ?? '' }
}

// The project the query tool and the org the billing tool really call, or null when the tool calls nothing.
async function targets(options: CallOptions): Promise<{ project: string | null; org: string | null }> {
    apiPaths.length = 0
    await postToolCall('execute-sql', { query: 'SELECT 1' }, options)
    const project = apiPaths.map((path) => /^\/api\/environments\/([^/]+)\//.exec(path)?.[1]).find(Boolean) ?? null
    apiPaths.length = 0
    await postToolCall('billing-subscription-get', {}, options)
    const org = apiPaths.map((path) => /^\/api\/organizations\/([^/]+)\//.exec(path)?.[1]).find(Boolean) ?? null
    apiPaths.length = 0
    return { project, org }
}

const tokenCache = (token: string): RedisCache<State> => new RedisCache<State>(hash(token), redis, 'token')

// The session store key that deployed servers used before it included the credential.
async function seedLegacySession(sessionId: string, state: Partial<SessionScopedState>): Promise<void> {
    const legacyPrefix = createHash('sha256').update(sessionId).digest().subarray(0, 16).toString('base64url')
    await new RedisCache<SessionScopedState>(legacyPrefix, redis, 'session', 3600).setMany(state)
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

        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })

        // The saved pin belongs to the credential: another token that reuses the session id keeps its own state.
        const otherToken = `phx_init_${kind}_other`
        await cacheOtherProjectOnToken(otherToken)
        expect(await targets({ token: otherToken, sessionId, query: '' })).toEqual({
            project: OTHER_PROJECT,
            org: OTHER_ORG,
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
    it('keeps an unpinned session on the shared token selection across repeated switches', async () => {
        const token = 'phx_unpinned_switches'
        const session = { token, sessionId: await initialize({ token, query: '' }), query: '' }
        const otherRequest = { token, query: '' }

        for (const [projectId, orgId] of [
            [OTHER_PROJECT, OTHER_ORG],
            [PINNED_PROJECT, PINNED_ORG],
            [OTHER_PROJECT, OTHER_ORG],
        ]) {
            expect((await callTool('switch-project', { projectId: Number(projectId) }, session)).isError).toBeFalsy()
            expect(await targets(session)).toEqual({ project: projectId, org: orgId })
            expect(await targets(otherRequest)).toEqual({ project: projectId, org: orgId })
        }
    })

    it.each([
        {
            label: 'a project pin replaced by an organization pin',
            initPin: `?project_id=${PINNED_PROJECT}`,
            switchTo: undefined,
            replacementPin: `?organization_id=${OTHER_ORG}`,
            expected: { project: OTHER_PROJECT, org: OTHER_ORG },
        },
        {
            label: 'an organization pin replaced by a project pin',
            initPin: `?organization_id=${OTHER_ORG}`,
            switchTo: undefined,
            replacementPin: `?project_id=${PINNED_PROJECT}`,
            expected: { project: PINNED_PROJECT, org: PINNED_ORG },
        },
        {
            label: 'a two-field pin that drops the organization',
            initPin: `?organization_id=${PINNED_ORG}&project_id=${PINNED_PROJECT}`,
            switchTo: OTHER_PROJECT,
            replacementPin: `?project_id=${PINNED_PROJECT}`,
            expected: { project: PINNED_PROJECT, org: PINNED_ORG },
        },
        {
            label: 'a two-field pin that drops the project',
            initPin: `?organization_id=${PINNED_ORG}&project_id=${PINNED_PROJECT}`,
            switchTo: OTHER_PROJECT,
            replacementPin: `?organization_id=${PINNED_ORG}`,
            expected: { project: PINNED_PROJECT, org: PINNED_ORG },
        },
    ])('replaces the whole saved pin for $label', async ({ label, initPin, switchTo, replacementPin, expected }) => {
        const token = `phx_replace_${label.replaceAll(' ', '_')}`
        await cacheOtherProjectOnToken(token)
        const sessionId = await initialize({ token, query: initPin })
        const switched = switchTo
            ? await callTool('switch-project', { projectId: Number(switchTo) }, { token, sessionId, query: initPin })
            : undefined
        expect(switched?.isError).toBeFalsy()

        expect(await targets({ token, sessionId, query: replacementPin })).toEqual(expected)
        // A later request that omits the pin restores only what the replacement pin set.
        expect(await targets({ token, sessionId, query: '' })).toEqual(expected)
    })

    const cacheDefaultProjectOnToken = async (token: string): Promise<void> => {
        expect(await targets({ token, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
    }
    const cacheMissingProjectOnToken = async (token: string): Promise<void> => {
        await tokenCache(token).set('projectId', MISSING_PROJECT)
    }

    it.each([
        {
            label: 'a cached project in another organization',
            seed: cacheDefaultProjectOnToken,
            pinnedOrg: OTHER_ORG,
            expected: { project: null, org: OTHER_ORG },
        },
        {
            label: 'no cached project and a default in another organization',
            seed: undefined,
            pinnedOrg: OTHER_ORG,
            expected: { project: null, org: OTHER_ORG },
        },
        {
            label: 'an inaccessible cached project',
            seed: cacheMissingProjectOnToken,
            pinnedOrg: OTHER_ORG,
            expected: { project: null, org: OTHER_ORG },
        },
        {
            label: 'a cached project in the pinned organization',
            seed: cacheOtherProjectOnToken,
            pinnedOrg: OTHER_ORG,
            expected: { project: OTHER_PROJECT, org: OTHER_ORG },
        },
        {
            label: 'no cached project and a default in the pinned organization',
            seed: undefined,
            pinnedOrg: PINNED_ORG,
            expected: { project: PINNED_PROJECT, org: PINNED_ORG },
        },
        {
            label: 'a cached project in another organization and a default in the pinned organization',
            seed: cacheOtherProjectOnToken,
            pinnedOrg: PINNED_ORG,
            expected: { project: PINNED_PROJECT, org: PINNED_ORG },
        },
    ])('limits an organization pin to its own projects with $label', async ({ label, seed, pinnedOrg, expected }) => {
        const token = `phx_org_pin_${label.replaceAll(' ', '_')}`
        await seed?.(token)
        const cachedBefore = await tokenCache(token).get('projectId')

        expect(await targets({ token, query: `?organization_id=${pinnedOrg}` })).toEqual(expected)
        // The org pin never writes its project choice into the selection that other requests share.
        expect(await tokenCache(token).get('projectId')).toEqual(cachedBefore)
    })

    it('keeps an explicit cross-organization switch in an organization-pinned session', async () => {
        const token = 'phx_org_pin_cross_switch'
        const pin = `?organization_id=${PINNED_ORG}`
        const sessionId = await initialize({ token, query: pin })
        const switched = await callTool(
            'switch-project',
            { projectId: Number(OTHER_PROJECT) },
            { token, sessionId, query: pin }
        )
        expect(switched.isError).toBeFalsy()

        expect(await targets({ token, sessionId, query: pin })).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
    })

    it.each([
        ['with the original pin resent', `?project_id=${PINNED_PROJECT}`],
        ['with the pin omitted', ''],
    ])('asks a switched session from before the credential-bound store to reconnect, %s', async (label, query) => {
        const token = `phx_legacy_${label.replaceAll(' ', '_')}`
        const sessionId = `legacy-session-${label.replaceAll(' ', '-')}`
        await seedLegacySession(sessionId, {
            appliedPinProjectId: PINNED_PROJECT,
            activeProjectId: OTHER_PROJECT,
            activeOrgId: OTHER_ORG,
        })

        for (const credential of [token, `${token}_other`]) {
            for (const [name, args] of [
                ['execute-sql', { query: 'SELECT 1' }],
                ['billing-subscription-get', {}],
            ] as const) {
                const response = await postToolCall(name, args, { token: credential, sessionId, query })
                expect(response).toMatchObject({ status: 200, error: { data: { reason: 'session_reset_required' } } })
                expect(response.result).toBeUndefined()
            }
        }
        expect(apiPaths).toEqual([])

        const freshSessionId = await initialize({ token, query: `?project_id=${PINNED_PROJECT}` })
        expect(await targets({ token, sessionId: freshSessionId, query: '' })).toEqual({
            project: PINNED_PROJECT,
            org: PINNED_ORG,
        })
    })

    it('ignores legacy session state that never held a pin', async () => {
        const token = 'phx_legacy_unpinned'
        const sessionId = 'legacy-session-unpinned'
        await cacheOtherProjectOnToken(token)
        await seedLegacySession(sessionId, { activeProjectId: PINNED_PROJECT, activeOrgId: PINNED_ORG })

        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
    })
})
