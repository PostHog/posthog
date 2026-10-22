import { http, HttpResponse, type DefaultBodyType, type StrictRequest } from 'msw'
import { setupServer } from 'msw/node'
import { createHash } from 'node:crypto'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { createApp } from '@/hono/app'
import { RedisCache, type RedisLike } from '@/hono/cache/RedisCache'
import { MCP_INTENT_PROMPT_FLAG } from '@/hono/intent-prompt'
import { MCP_INTERVIEW_RECRUITMENT_FLAG } from '@/hono/interview-recruitment'
import { RequestStateResolver } from '@/hono/request-state-resolver'
import * as constants from '@/lib/constants'
import { getPostHogClient } from '@/lib/posthog'
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
const apiPathsByIntent = new Map<string, string[]>()

function recordApiPath(request: StrictRequest<DefaultBodyType>): void {
    const path = new URL(request.url).pathname
    apiPaths.push(path)
    const intent = request.headers.get('x-posthog-intent')
    if (intent) {
        const paths = apiPathsByIntent.get(intent) ?? []
        paths.push(path)
        apiPathsByIntent.set(intent, paths)
    }
}

const mswServer = setupServer(
    http.get('*/api/projects/:projectId/integrations/', () => HttpResponse.json({ results: [] })),
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
        recordApiPath(request)
        return HttpResponse.json({ success: true, content: 'ok' })
    }),
    http.post('*/api/projects/:projectId/feature_flags/', ({ request }) => {
        recordApiPath(request)
        return HttpResponse.json({ id: 123, key: 'batch-routing', active: true, filters: { groups: [] } })
    }),
    http.get('*/api/organizations/:orgId/billing/subscription/', ({ request }) => {
        recordApiPath(request)
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
        set: async (key, value, ...args) => {
            if (args.includes('NX') && store.has(key)) {
                return null
            }
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async (_cursor, ...args) => {
            const match = args.indexOf('MATCH')
            const prefix = match === -1 ? '' : String(args[match + 1]).replace(/\*$/, '')
            return ['0', Array.from(store.keys()).filter((key) => key.startsWith(prefix))] as [string, string[]]
        },
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

afterEach(() => {
    mswServer.resetHandlers()
})

type CallOptions = {
    // Each test uses its own token, so the shared token cache never carries state between tests.
    token?: string
    query?: string
    sessionId?: string
    conversationId?: string
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
    { query = `?project_id=${PINNED_PROJECT}`, conversationId, ...options }: CallOptions = {}
): Promise<ToolCallResponse> {
    const response = await app.request(`/mcp${query}`, {
        method: 'POST',
        headers: requestHeaders(options),
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method: 'tools/call',
            params: { name, arguments: conversationId ? { ...args, conversation_id: conversationId } : args },
        }),
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

async function postBatch(
    calls: Array<{ name: string; arguments: Record<string, unknown> }>,
    options: CallOptions
): Promise<Array<Omit<ToolCallResponse, 'status'>>> {
    const response = await app.request(`/mcp${options.query ?? ''}`, {
        method: 'POST',
        headers: requestHeaders(options),
        body: JSON.stringify(calls.map((params, id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params }))),
    })
    return (await response.json()) as Array<Omit<ToolCallResponse, 'status'>>
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

const CONVERSATION_A = '0199c6f0-0000-7000-8000-00000000000a'
const CONVERSATION_B = '0199c6f0-0000-7000-8000-00000000000b'

function mintedConversationId(response: ToolCallResponse): string | undefined {
    const prompt = response.result?.content?.find((item) => item.text?.startsWith('{"conversation_id"'))
    return prompt ? (JSON.parse(prompt.text!) as { conversation_id: string }).conversation_id : undefined
}

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

async function cacheOtherProjectOnToken(token: string): Promise<void> {
    await tokenCache(token).setMany({ projectId: OTHER_PROJECT, orgId: OTHER_ORG })
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

    it.each([
        ['project', `?project_id=${PINNED_PROJECT}`],
        ['organization', `?organization_id=${PINNED_ORG}`],
    ])('keeps a %s pin sent only on initialize for later requests in the session', async (kind, pinQuery) => {
        const token = `phx_init_${kind}`
        await cacheOtherProjectOnToken(token)

        const sessionId = await initialize({ token, query: pinQuery })

        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        expect(
            (await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, { token, sessionId, query: '' }))
                .isError
        ).toBeFalsy()

        // The saved pin belongs to the credential: another token that reuses the session id keeps its own state.
        const otherToken = `phx_init_${kind}_other`
        await cacheOtherProjectOnToken(otherToken)
        expect(await targets({ token: otherToken, sessionId, query: '' })).toEqual({
            project: PINNED_PROJECT,
            org: PINNED_ORG,
        })
        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
    })

    it("reports missing context instead of using another session's org when the pinned project lookup fails", async () => {
        const token = 'phx_missing_project'
        await cacheOtherProjectOnToken(token)

        const result = await runBilling({ token, query: `?project_id=${MISSING_PROJECT}` })

        expect(result.isError).toBe(true)
        expect(result.paths).toEqual([])
    })

    it.each([
        ['unpinned conversation', ''],
        ['pinned conversation', `?project_id=${PINNED_PROJECT}`],
    ])('isolates each %s without changing credential defaults', async (label, query) => {
        const token = `phx_${label.replaceAll(' ', '_')}`
        const first = { token, query, conversationId: CONVERSATION_A }
        const second = { token, query, conversationId: CONVERSATION_B }
        expect((await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, first)).isError).toBeFalsy()
        expect((await callTool('switch-project', { projectId: Number(PINNED_PROJECT) }, second)).isError).toBeFalsy()

        expect(await targets(first)).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
        expect(await targets(second)).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        expect(await tokenCache(token).get('projectId')).toBeUndefined()
    })

    it.each(
        [
            {
                tool: 'switch-project',
                args: { projectId: Number(OTHER_PROJECT) },
                expected: { project: OTHER_PROJECT, org: OTHER_ORG },
            },
            {
                tool: 'switch-organization',
                args: { orgId: OTHER_ORG },
                expected: { project: null, org: OTHER_ORG },
            },
        ].flatMap((testCase) =>
            ['', `?project_id=${PINNED_PROJECT}`, '?sessionId=wrapper-context'].flatMap((query) =>
                ['direct', 'exec'].map((mode) => ({ ...testCase, query, mode }))
            )
        )
    )(
        'requires a carried handle before $mode $tool with pin "$query"',
        async ({ tool, args, expected, query, mode }) => {
            const token = `phx_require_handle_${tool}_${mode}_${query}`
            const toolName = mode === 'exec' ? 'exec' : tool
            const toolArgs = mode === 'exec' ? { command: `call ${tool} ${JSON.stringify(args)}` } : args
            const first = await postToolCall(toolName, toolArgs, { token, query })
            expect(first.result?.isError).toBe(true)
            expect(first.result?.content?.[0]?.text).toContain('Retry with the returned `conversation_id`')
            const conversationId = mintedConversationId(first)
            expect(conversationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7/)
            const defaults = { project: PINNED_PROJECT, org: PINNED_ORG }
            expect(await targets({ token, query, conversationId })).toEqual(defaults)
            expect(await targets({ token, query })).toEqual(defaults)

            const retry = await postToolCall(toolName, toolArgs, { token, query, conversationId })
            expect(retry.result?.isError).toBeFalsy()
            expect(await targets({ token, query, conversationId })).toEqual(expected)
            expect(await targets({ token, query })).toEqual(defaults)
        }
    )

    it.each([undefined, 'conv-1'])(
        'rejects batch handles %s and accepts retries with minted handles',
        async (supplied) => {
            const token = `phx_batch_requires_handle_${supplied}`
            const calls = [
                { name: 'switch-project', arguments: { projectId: Number(OTHER_PROJECT) } },
                { name: 'switch-organization', arguments: { orgId: OTHER_ORG } },
            ]
            const results = await postBatch(
                calls.map((call) => ({ ...call, arguments: { ...call.arguments, conversation_id: supplied } })),
                { token }
            )
            expect(results.map(({ result }) => result?.isError)).toEqual([true, true])
            const handles = results.map((result) => mintedConversationId({ status: 200, ...result }))
            expect(handles).toEqual([
                expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-7/),
                expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-7/),
            ])
            expect(new Set(handles).size).toBe(2)
            expect(await targets({ token, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })

            const retries = await postBatch(
                calls.map((call, index) => ({
                    ...call,
                    arguments: { ...call.arguments, conversation_id: handles[index] },
                })),
                { token }
            )
            expect(retries.map(({ result }) => Boolean(result?.isError))).toEqual([false, false])
            expect(await targets({ token, query: '', conversationId: handles[0] })).toEqual({
                project: OTHER_PROJECT,
                org: OTHER_ORG,
            })
            expect(await targets({ token, query: '', conversationId: handles[1] })).toEqual({
                project: null,
                org: OTHER_ORG,
            })
            expect(await targets({ token, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        }
    )

    it.each(['direct', 'exec'])('validates each handle independently in a mixed %s batch', async (mode) => {
        const token = `phx_mixed_batch_${mode}`
        const results = await postBatch(
            [CONVERSATION_A, 'conv-1'].map((conversation_id) => ({
                name: mode === 'exec' ? 'exec' : 'switch-project',
                arguments: {
                    ...(mode === 'exec'
                        ? { command: `call switch-project {"projectId":${OTHER_PROJECT}}` }
                        : { projectId: Number(OTHER_PROJECT) }),
                    conversation_id,
                },
            })),
            { token }
        )
        expect(results.map(({ result }) => Boolean(result?.isError))).toEqual([false, true])
        expect(await targets({ token, query: '', conversationId: CONVERSATION_A })).toEqual({
            project: OTHER_PROJECT,
            org: OTHER_ORG,
        })
    })

    it.each(
        [
            {
                operation: 'read',
                name: 'execute-sql',
                args: { query: 'SELECT 1' },
                route: (project: string) => `/api/environments/${project}/mcp_tools/execute_sql/`,
            },
            {
                operation: 'write through exec',
                name: 'exec',
                args: { command: 'call create-feature-flag {"key":"batch-routing","filters":{"groups":[]}}' },
                route: (project: string) => `/api/projects/${project}/feature_flags/`,
            },
        ].flatMap((operation) => [false, true].map((differentHandles) => ({ ...operation, differentHandles })))
    )(
        'isolates batch $operation with different handles=$differentHandles',
        async ({ name, args, route, operation, differentHandles }) => {
            const token = `phx_batch_routing_${operation.replaceAll(' ', '_')}_${differentHandles}`
            const conversations = [CONVERSATION_A, differentHandles ? CONVERSATION_B : CONVERSATION_A]
            const projects = [OTHER_PROJECT, differentHandles ? '3' : OTHER_PROJECT]
            for (const [conversationId, projectId] of new Map(
                conversations.map((conversationId, index) => [conversationId, projects[index]!])
            )) {
                expect(
                    (
                        await callTool(
                            'switch-project',
                            { projectId: Number(projectId) },
                            { token, query: '', conversationId }
                        )
                    ).isError
                ).toBeFalsy()
            }
            apiPathsByIntent.clear()
            const results = await postBatch(
                conversations.map((conversation_id, index) => ({
                    name,
                    arguments: { ...args, conversation_id, context: `batch-item-${index}` },
                })),
                { token }
            )
            expect(results.map(({ result }) => Boolean(result?.isError))).toEqual([false, false])
            expect(projects.map((_, index) => apiPathsByIntent.get(`batch-item-${index}`))).toEqual(
                projects.map((project) => [route(project)])
            )
        }
    )

    it('returns an individual error when one batch context lookup fails', async () => {
        const originalResolve = RequestStateResolver.prototype.resolve
        const resolve = vi
            .spyOn(RequestStateResolver.prototype, 'resolve')
            .mockImplementation(function (this: RequestStateResolver, props) {
                return props.mcpConversationId === CONVERSATION_A
                    ? Promise.reject(new Error('Synthetic batch context failure'))
                    : originalResolve.call(this, props)
            })
        apiPaths.length = 0
        try {
            const results = await postBatch(
                [CONVERSATION_A, CONVERSATION_B].map((conversation_id) => ({
                    name: 'execute-sql',
                    arguments: { query: 'SELECT 1', conversation_id },
                })),
                { token: 'phx_batch_context_failure' }
            )
            expect({
                responses: results.map(({ error, result }) => error?.code ?? Boolean(result?.isError)),
                paths: apiPaths,
            }).toEqual({
                responses: [-32603, false],
                paths: [`/api/environments/${PINNED_PROJECT}/mcp_tools/execute_sql/`],
            })
        } finally {
            resolve.mockRestore()
        }
    })

    it.each([
        {
            handles: 'repeated',
            conversations: [CONVERSATION_A, CONVERSATION_A],
            projects: [OTHER_PROJECT, OTHER_PROJECT],
            scopedOrg: false,
        },
        {
            handles: 'different',
            conversations: [CONVERSATION_A, CONVERSATION_B],
            projects: [OTHER_PROJECT, PINNED_PROJECT],
            scopedOrg: false,
        },
        { handles: 'missing', conversations: [], projects: [PINNED_PROJECT, PINNED_PROJECT], scopedOrg: false },
        { handles: 'org-default', conversations: [], projects: [OTHER_PROJECT, OTHER_PROJECT], scopedOrg: true },
    ])(
        'shares cold batch lookups with $handles conversation handles while preserving routing',
        async ({ handles, conversations, projects, scopedOrg }) => {
            const token = `phx_cold_batch_${handles}`
            if (scopedOrg) {
                mswServer.use(
                    http.get('*/api/personal_api_keys/@current', () =>
                        HttpResponse.json({ scopes: ['*'], scoped_teams: [], scoped_organizations: [OTHER_ORG] })
                    ),
                    http.get(`*/api/organizations/${OTHER_ORG}/projects/`, () =>
                        HttpResponse.json({ results: [{ id: Number(OTHER_PROJECT), organization: OTHER_ORG }] })
                    )
                )
            }
            for (const [conversationId, projectId] of new Map(
                conversations.map((id, index) => [id, projects[index]!])
            )) {
                expect(
                    (
                        await callTool(
                            'switch-project',
                            { projectId: Number(projectId) },
                            { token, query: '', conversationId }
                        )
                    ).isError
                ).toBeFalsy()
            }
            await tokenCache(token).clear()
            apiPathsByIntent.clear()
            const counts = new Map<string, number>()
            const record = ({ request }: { request: Request }): void => {
                const path = new URL(request.url).pathname
                counts.set(path, (counts.get(path) ?? 0) + 1)
            }
            mswServer.events.on('request:start', record)
            const localApi = vi.spyOn(constants, 'isLocalApi').mockReturnValue(false)
            const flags = vi
                .spyOn(getPostHogClient(), 'getAllFlagsAndPayloads')
                .mockImplementation(async (_distinctId, options) => ({
                    featureFlags: Object.fromEntries(
                        (options?.flagKeys ?? []).map((key) => [
                            key,
                            key !== MCP_INTERVIEW_RECRUITMENT_FLAG && key !== MCP_INTENT_PROMPT_FLAG,
                        ])
                    ),
                    featureFlagPayloads: {},
                }))
            try {
                const results = await postBatch(
                    Array.from({ length: 100 }, (_, index) => ({
                        name: 'execute-sql',
                        arguments: {
                            query: 'SELECT 1',
                            conversation_id: conversations[index % 2],
                            context: `cold-item-${index}`,
                        },
                    })),
                    { token }
                )
                expect(results.map(({ result }) => Boolean(result?.isError))).toEqual(Array(100).fill(false))
                expect(counts.get('/api/personal_api_keys/@current')).toBe(1)
                expect(counts.get('/api/users/@me/')).toBe(1)
                expect(flags).toHaveBeenCalledTimes(new Set(projects).size)
                expect(counts.get(`/api/organizations/${OTHER_ORG}/projects/`) ?? 0).toBe(scopedOrg ? 1 : 0)
                for (const project of new Set(projects)) {
                    const org = project === OTHER_PROJECT ? OTHER_ORG : PINNED_ORG
                    expect(counts.get(`/api/projects/${project}/`)).toBe(1)
                    expect(counts.get(`/api/organizations/${org}/`)).toBe(1)
                }
                expect(Array.from({ length: 100 }, (_, index) => apiPathsByIntent.get(`cold-item-${index}`))).toEqual(
                    Array.from({ length: 100 }, (_, index) => [
                        `/api/environments/${projects[index % 2]}/mcp_tools/execute_sql/`,
                    ])
                )
            } finally {
                mswServer.events.removeListener('request:start', record)
                flags.mockRestore()
                localApi.mockRestore()
            }
        }
    )

    it('keeps a conversation bound to its credential and separate from a transport session with the same id', async () => {
        const token = 'phx_conversation_namespace'
        const conversation = { token, query: '', conversationId: CONVERSATION_A }
        await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, conversation)

        expect(
            await targets({ token: 'phx_other_conversation_namespace', query: '', conversationId: CONVERSATION_A })
        ).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        expect(await targets({ token, query: '', sessionId: CONVERSATION_A })).toEqual({
            project: PINNED_PROJECT,
            org: PINNED_ORG,
        })
        expect(await targets({ token, query: '', sessionId: CONVERSATION_A, conversationId: CONVERSATION_A })).toEqual({
            project: PINNED_PROJECT,
            org: PINNED_ORG,
        })
        expect(await targets(conversation)).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
    })

    it.each(['conv-1', CONVERSATION_A.toUpperCase()])(
        'uses the SDK-normalized conversation identity for %s',
        async (supplied) => {
            const token = `phx_normalize_${supplied}`
            const first = await postToolCall(
                'switch-project',
                { projectId: Number(OTHER_PROJECT) },
                { token, query: '', conversationId: supplied }
            )
            expect(Boolean(first.result?.isError)).toBe(supplied === 'conv-1')
            const conversationId = supplied === 'conv-1' ? mintedConversationId(first) : CONVERSATION_A
            expect(conversationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7/)
            const retry = await callTool(
                'switch-project',
                { projectId: Number(OTHER_PROJECT) },
                { token, query: '', conversationId }
            )
            expect(retry.isError).toBeFalsy()

            expect(await targets({ token, query: '', conversationId })).toEqual({
                project: OTHER_PROJECT,
                org: OTHER_ORG,
            })
            expect(await targets({ token, query: '', conversationId: supplied })).toEqual(
                supplied === 'conv-1'
                    ? { project: PINNED_PROJECT, org: PINNED_ORG }
                    : { project: OTHER_PROJECT, org: OTHER_ORG }
            )
        }
    )

    it.each([
        ['pinned across organizations', `?project_id=${PINNED_PROJECT}`, OTHER_PROJECT, OTHER_ORG],
        ['unpinned across organizations', '', OTHER_PROJECT, OTHER_ORG],
        ['unpinned within an organization', '', '3', PINNED_ORG],
    ])('isolates %s across repeated switches', async (label, query, switchedProject, switchedOrg) => {
        const token = `phx_${label.replaceAll(' ', '_')}_switches`
        const session = { token, sessionId: await initialize({ token, query }), query }
        const otherSession = { token, sessionId: await initialize({ token, query }), query }

        for (const [projectId, orgId] of [
            [switchedProject, switchedOrg],
            [PINNED_PROJECT, PINNED_ORG],
            [switchedProject, switchedOrg],
        ]) {
            expect((await callTool('switch-project', { projectId: Number(projectId) }, session)).isError).toBeFalsy()
            expect(await targets(session)).toEqual({ project: projectId, org: orgId })
            expect(await targets(otherSession)).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        }
    })

    it('starts an unpinned session from the user default instead of another connection’s token selection', async () => {
        const token = 'phx_unpinned_default'
        await cacheOtherProjectOnToken(token)
        const sessionId = await initialize({ token, query: '' })

        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
    })

    it.each([
        ['unpinned session', '', undefined],
        ['organization-pinned session', `?organization_id=${PINNED_ORG}`, undefined],
        ['unpinned conversation', '', CONVERSATION_A],
        ['organization-pinned conversation', `?organization_id=${PINNED_ORG}`, CONVERSATION_A],
    ])('keeps a %s on its project when the website selection changes', async (label, query, conversationId) => {
        const token = `phx_website_selection_${label}`
        const sessionId = conversationId ? undefined : await initialize({ token, query })
        const connection = { token, sessionId, conversationId, query }
        await targets(connection)
        const user = {
            distinct_id: 'website-selection-test',
            email: 'test@example.com',
            team: { id: Number(OTHER_PROJECT), name: 'Other project', organization: OTHER_ORG },
            organization: { id: OTHER_ORG, name: 'Other organization' },
        }
        mswServer.use(http.get('*/api/users/@me/', () => HttpResponse.json(user)))
        const newSessionId = await initialize({ token, query: '' })

        expect(await targets(connection)).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
        expect(await targets({ token, sessionId: newSessionId, query: '' })).toEqual({
            project: OTHER_PROJECT,
            org: OTHER_ORG,
        })
    })

    it.each(['session', 'conversation'])(
        'routes overlapping calls from each %s to its own organization and project',
        async (kind) => {
            const token = `phx_concurrent_${kind}`
            const sessions = await Promise.all(
                [PINNED_PROJECT, OTHER_PROJECT].map(async (projectId) => {
                    const session = {
                        token,
                        ...(kind === 'session'
                            ? { sessionId: await initialize({ token, query: '' }) }
                            : { conversationId: projectId === PINNED_PROJECT ? CONVERSATION_A : CONVERSATION_B }),
                        query: '',
                    }
                    const result = await callTool('switch-project', { projectId: Number(projectId) }, session)
                    expect(result.isError).toBeFalsy()
                    return session
                })
            )
            apiPaths.length = 0
            apiPathsByIntent.clear()

            const pathsBySession = await Promise.all(
                sessions.map(async (session, index) => {
                    const context = `concurrent-session-${index}`
                    await Promise.all([
                        callTool('execute-sql', { query: 'SELECT 1', context }, session),
                        callTool('billing-subscription-get', { context }, session),
                    ])
                    return [...(apiPathsByIntent.get(context) ?? [])].sort()
                })
            )

            expect(pathsBySession).toEqual([
                pathsFor(PINNED_PROJECT, PINNED_ORG).sort(),
                pathsFor(OTHER_PROJECT, OTHER_ORG).sort(),
            ])
        }
    )

    it.each([
        ['pinned', `?project_id=${PINNED_PROJECT}`],
        ['unpinned', ''],
    ])('clears the previous project when a %s session switches organizations', async (label, query) => {
        const token = `phx_${label}_org_switch`
        const session = { token, sessionId: await initialize({ token, query }), query }
        expect((await callTool('switch-organization', { orgId: OTHER_ORG }, session)).isError).toBeFalsy()

        expect(await targets(session)).toEqual({ project: null, org: OTHER_ORG })
        expect((await callTool('switch-project', { projectId: Number(OTHER_PROJECT) }, session)).isError).toBeFalsy()
        expect(await targets(session)).toEqual({ project: OTHER_PROJECT, org: OTHER_ORG })
    })

    it.each([
        ['same organization', PINNED_ORG, PINNED_PROJECT],
        ['different organization', OTHER_ORG, null],
    ])('keeps project ownership consistent for a %s switch without project:read', async (label, orgId, project) => {
        const token = `phx_no_project_read_${label.replaceAll(' ', '_')}`
        mswServer.use(
            http.get('*/api/projects/:projectId/', () =>
                HttpResponse.json({ detail: 'Missing project:read' }, { status: 403 })
            ),
            http.get('*/api/organizations/:orgId/', ({ params }) =>
                HttpResponse.json({
                    id: params.orgId,
                    name: 'Organization',
                    teams: [{ id: params.orgId === PINNED_ORG ? Number(PINNED_PROJECT) : Number(OTHER_PROJECT) }],
                })
            )
        )
        const query = `?project_id=${PINNED_PROJECT}`
        const session = { token, sessionId: await initialize({ token, query }), query }
        expect((await callTool('switch-organization', { orgId }, session)).isError).toBeFalsy()

        expect(await targets(session)).toEqual({ project, org: orgId })
    })

    it('preserves the session selection when the destination organization is inaccessible', async () => {
        const token = 'phx_inaccessible_organization'
        const session = { token, sessionId: await initialize({ token, query: '' }), query: '' }
        mswServer.use(
            http.get(`*/api/organizations/${OTHER_ORG}/`, () =>
                HttpResponse.json({ detail: 'Not found.' }, { status: 404 })
            )
        )

        const result = await callTool('switch-organization', { orgId: OTHER_ORG }, session)

        expect(result.isError).toBe(true)
        expect(await targets(session)).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
    })

    it.each([
        {
            label: 'a project pin replaced by an organization pin',
            initPin: `?project_id=${PINNED_PROJECT}`,
            switchTo: undefined,
            replacementPin: `?organization_id=${OTHER_ORG}`,
            expected: { project: null, org: OTHER_ORG },
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
            expected: { project: null, org: OTHER_ORG },
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

        expect(await targets({ token, sessionId, query: '' })).toEqual({ project: PINNED_PROJECT, org: PINNED_ORG })
    })
})
