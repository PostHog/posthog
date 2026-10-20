import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const {
    mockBuildInstructions,
    mockInitDurationObserve,
    mockInitTotalInc,
    mockRevalidateContextMillResources,
    mockResolveState,
    mockSkillCatalogService,
    mockTrackInitEvent,
} = vi.hoisted(() => ({
    mockBuildInstructions: vi.fn(),
    mockInitDurationObserve: vi.fn(),
    mockInitTotalInc: vi.fn(),
    mockRevalidateContextMillResources: vi.fn(),
    mockResolveState: vi.fn(),
    mockSkillCatalogService: {
        getCatalog: vi.fn(),
        poll: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        warmup: vi.fn(),
    },
    mockTrackInitEvent: vi.fn(),
}))

vi.mock('@/hono/skill-catalog-service', () => ({
    SkillCatalogService: vi.fn().mockImplementation(function () {
        return mockSkillCatalogService
    }),
}))

vi.mock('@/hono/analytics', () => ({
    trackInitEvent: mockTrackInitEvent,
}))

vi.mock('@/hono/instructions', () => ({
    InstructionsBuilder: vi.fn().mockImplementation(function () {
        return {
            build: mockBuildInstructions,
        }
    }),
}))

vi.mock('@/hono/metrics', () => ({
    initDurationSeconds: { observe: mockInitDurationObserve },
    initTotal: { inc: mockInitTotalInc },
}))

vi.mock('@/hono/request-state-resolver', () => ({
    RequestStateResolver: vi.fn().mockImplementation(function () {
        return {
            resolve: mockResolveState,
        }
    }),
}))

vi.mock('@/hono/resource-catalog', () => ({
    ResourceCatalog: vi.fn().mockImplementation(function () {
        return {
            getPrompt: vi.fn(() => ({ messages: [] })),
            getPromptsList: vi.fn(() => ({ prompts: [] })),
            getResourcesList: vi.fn(() => ({ resources: [] })),
            readResource: vi.fn(async () => ({ contents: [] })),
            revalidateContextMillResources: mockRevalidateContextMillResources,
            warmup: vi.fn(async () => {}),
        }
    }),
}))

import { LATEST_PROTOCOL_VERSION } from '@modelcontextprotocol/sdk/types.js'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { McpDispatcher } from '@/hono/dispatcher'
import { PostHogRateLimitError, PostHogValidationError } from '@/lib/errors'
import type { RequestProperties } from '@/lib/request-properties'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

function createMockRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => {
            let count = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    count++
                }
            }
            return count
        }),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...makeRedisRateLimitStubs(),
    }
}

function makeProps(): RequestProperties {
    return {
        apiToken: 'phx_test',
        mcpClientName: 'test-client',
        mcpClientVersion: '1.0.0',
        mcpProtocolVersion: LATEST_PROTOCOL_VERSION,
        requestStartTime: Date.now(),
        transport: 'streamable-http',
        userHash: 'test-user',
    }
}

function makeInitializeRequest(): Request {
    return new Request('https://mcp.test/mcp', {
        body: JSON.stringify({
            id: 1,
            jsonrpc: '2.0',
            method: 'initialize',
            params: {
                capabilities: {},
                clientInfo: { name: 'test-client', version: '1.0.0' },
                protocolVersion: LATEST_PROTOCOL_VERSION,
            },
        }),
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
    })
}

describe('McpDispatcher initialize resource revalidation', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockBuildInstructions.mockResolvedValue('')
        mockResolveState.mockResolvedValue({ distinctId: 'test-distinct-id' })
        mockTrackInitEvent.mockResolvedValue(undefined)
        mockRevalidateContextMillResources.mockResolvedValue(undefined)
        mockSkillCatalogService.warmup.mockReset().mockResolvedValue(undefined)
    })

    afterEach(() => vi.unstubAllEnvs())

    it('awaits context-mill resource revalidation before returning initialize', async () => {
        let resolveRevalidation: (() => void) | undefined
        const revalidationPromise = new Promise<void>((resolve) => {
            resolveRevalidation = resolve
        })
        mockRevalidateContextMillResources.mockReturnValueOnce(revalidationPromise)

        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const responsePromise = dispatcher.handleRequest(makeInitializeRequest(), makeProps())
        let responseSettled = false
        void responsePromise.then(() => {
            responseSettled = true
        })

        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(mockRevalidateContextMillResources).toHaveBeenCalledWith('initialize')
        expect(responseSettled).toBe(false)

        resolveRevalidation!()
        const response = await responsePromise
        const body = (await response.json()) as any

        expect(response.status).toBe(200)
        expect(body.result.protocolVersion).toBe(LATEST_PROTOCOL_VERSION)
        expect(mockBuildInstructions).toHaveBeenCalled()
    })

    // The reverted skill discovery revalidated the skill archive on every handshake,
    // which re-read megabytes from Redis per session. The archive moves only at warmup
    // and on the service's own timer.
    it('does no skill archive work on initialize', async () => {
        const dispatcher = new McpDispatcher({} as any, createMockRedis())

        const response = await dispatcher.handleRequest(makeInitializeRequest(), makeProps())

        expect(response.status).toBe(200)
        for (const method of ['warmup', 'poll', 'start'] as const) {
            expect(mockSkillCatalogService[method]).not.toHaveBeenCalled()
        }
    })

    it.each([
        ['development', false, false],
        ['test', false, false],
        ['development', true, true],
        ['development', undefined, true],
        ['production', false, true],
    ] as const)('honors startup overrides only in dev/test (%s, flag %s)', async (nodeEnv, override, enabled) => {
        vi.stubEnv('NODE_ENV', nodeEnv)
        vi.stubEnv('FEATURE_FLAG_OVERRIDES', JSON.stringify({ 'mcp-exec-skills': override }))
        if (!enabled) {
            mockSkillCatalogService.warmup.mockRejectedValue(new Error('archive unavailable'))
        }
        const dispatcher = new McpDispatcher({ warmup: vi.fn(async () => {}) } as any, createMockRedis())

        await dispatcher.warmup()

        expect(mockSkillCatalogService.warmup).toHaveBeenCalledTimes(enabled ? 1 : 0)
        expect(mockSkillCatalogService.start).toHaveBeenCalledTimes(enabled ? 1 : 0)
        if (enabled) {
            expect(mockSkillCatalogService.start.mock.invocationCallOrder[0]).toBeGreaterThan(
                mockSkillCatalogService.warmup.mock.invocationCallOrder[0]!
            )
        }
    })
})

function eventRequest(method: string, params: Record<string, unknown> = {}, modern = true): Request {
    const body = {
        jsonrpc: '2.0',
        id: 42,
        method,
        params: {
            ...params,
            ...(modern
                ? {
                      _meta: {
                          'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                          'io.modelcontextprotocol/clientInfo': { name: 'test-events', version: '1.0' },
                          'io.modelcontextprotocol/clientCapabilities': {},
                      },
                  }
                : {}),
        },
    }
    return new Request('https://mcp.test/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(modern ? { 'Mcp-Protocol-Version': '2026-07-28', 'Mcp-Method': method } : {}),
            ...(typeof params.name === 'string' ? { 'Mcp-Name': params.name } : {}),
        },
        body: JSON.stringify(body),
    })
}

describe('McpDispatcher event subscriptions', () => {
    const requestApi = vi.fn()
    const subscription = {
        name: 'posthog.event_captured',
        arguments: { project_id: 23, filters: { source: 'events', events: [{ id: 'example_event', type: 'events' }] } },
        delivery: { mode: 'webhook', url: 'https://example.com/callback', secret: 'whsec_test' },
        ttlMs: 60_000,
    }
    beforeEach(() => {
        vi.clearAllMocks()
        mockBuildInstructions.mockReturnValue('Base instructions')
        mockResolveState.mockResolvedValue({
            distinctId: 'test-distinct-id',
            toolFeatureFlags: { 'mcp-events': true },
            apiKeyScopes: ['mcp_event_subscription:write', 'query:read'],
            context: { api: { request: requestApi } },
        })
        requestApi.mockResolvedValue({ id: 'test-subscription', expires_at: '2026-10-15T12:00:00Z' })
        mockRevalidateContextMillResources.mockResolvedValue(undefined)
    })

    it.each([
        [true, ['mcp_event_subscription:write', 'query:read'], false, true],
        [false, ['mcp_event_subscription:write', 'query:read'], false, false],
        [true, ['query:read'], false, false],
        [true, ['mcp_event_subscription:write', 'query:read'], true, false],
    ])('gates discovery on flag %s, scopes %s and read-only %s', async (flag, scopes, readOnly, enabled) => {
        const state = await mockResolveState()
        mockResolveState.mockResolvedValue({ ...state, toolFeatureFlags: { 'mcp-events': flag }, apiKeyScopes: scopes })
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const response = await dispatcher.handleRequest(eventRequest('server/discover'), { ...makeProps(), readOnly })
        const body = (await response.json()) as any
        expect('events' in body.result.capabilities).toBe(enabled)
        expect(body.result.instructions.includes('mcp-events-preview')).toBe(enabled)
    })

    it('discovers per-account filters, adapts subscription fields and tears down by callback identity', async () => {
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const listed = await dispatcher.handleRequest(eventRequest('events/list'), makeProps())
        const catalog = (await listed.json()) as any
        expect(catalog.result.events[0].name).toBe(subscription.name)
        expect(catalog.result.events[0].inputSchema.properties.filters).toBeTruthy()
        expect(catalog.result.events[0].payloadSchema.properties.properties).toBeTruthy()
        expect(catalog.result.cacheScope).toBe('private')
        const created = await dispatcher.handleRequest(eventRequest('events/subscribe', subscription), makeProps())
        expect(((await created.json()) as any).result).toMatchObject({
            id: 'test-subscription',
            refreshBefore: '2026-10-15T12:00:00Z',
            cursor: null,
            truncated: false,
        })
        expect(requestApi).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/23/mcp_event_subscriptions/subscribe/',
            body: {
                name: subscription.name,
                arguments: subscription.arguments,
                delivery: subscription.delivery,
                ttl_ms: 60_000,
                cursor: null,
            },
        })
        const stopped = {
            name: subscription.name,
            arguments: subscription.arguments,
            delivery: { mode: 'webhook', url: subscription.delivery.url },
        }
        const response = await dispatcher.handleRequest(eventRequest('events/unsubscribe', stopped), makeProps())
        expect(((await response.json()) as any).result.resultType).toBe('complete')
        expect(requestApi).toHaveBeenLastCalledWith({
            method: 'POST',
            path: '/api/projects/23/mcp_event_subscriptions/unsubscribe/',
            body: stopped,
        })
    })

    it('rejects unknown filters instead of silently broadening a subscription', async () => {
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const response = await dispatcher.handleRequest(
            eventRequest('events/subscribe', {
                ...subscription,
                arguments: { project_id: 23, filters: { unexpected_condition: 'would otherwise be ignored' } },
            }),
            makeProps()
        )
        expect(((await response.json()) as any).error.code).toBe(-32602)
        expect(requestApi).not.toHaveBeenCalled()
    })

    it('returns categorized callback verification errors without logging secrets', async () => {
        requestApi.mockRejectedValue(
            new PostHogValidationError({
                detail: 'timeout',
                attr: 'callback__reason',
                code: 'invalid_input',
                extra: undefined,
                url: 'https://example.com/api',
                method: 'POST',
            })
        )
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const response = await dispatcher.handleRequest(eventRequest('events/subscribe', subscription), makeProps())
        const body = (await response.json()) as any
        expect(body.error).toEqual({
            code: -32015,
            message: 'Callback verification failed.',
            data: { reason: 'timeout' },
        })
        expect(JSON.stringify(body)).not.toContain(subscription.delivery.secret)
    })

    it('preserves upstream throttle delay without exposing request details', async () => {
        requestApi.mockRejectedValue(
            new PostHogRateLimitError({
                retryAfterSeconds: 45,
                body: 'private upstream details',
                url: 'https://example.com/api',
                method: 'POST',
            })
        )
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const response = await dispatcher.handleRequest(eventRequest('events/subscribe', subscription), makeProps())
        const body = (await response.json()) as any
        expect(body.error).toEqual({
            code: -32000,
            message: 'PostHog rate limited this subscription request. Retry after the indicated delay.',
            data: { retryAfterSeconds: 45 },
        })
        expect(JSON.stringify(body)).not.toContain('private upstream details')
        expect(JSON.stringify(body)).not.toContain('https://example.com/api')
    })

    it('keeps legacy event requests unsupported', async () => {
        const dispatcher = new McpDispatcher({} as any, createMockRedis())
        const response = await dispatcher.handleRequest(
            eventRequest('events/subscribe', subscription, false),
            makeProps()
        )
        expect(((await response.json()) as any).error.code).toBe(-32601)
        expect(requestApi).not.toHaveBeenCalled()
    })
})
