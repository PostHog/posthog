import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
    mockBuildInstructions,
    mockInitDurationObserve,
    mockInitTotalInc,
    mockRevalidateContextMillResources,
    mockResolveState,
    mockTrackInitEvent,
} = vi.hoisted(() => ({
    mockBuildInstructions: vi.fn(),
    mockInitDurationObserve: vi.fn(),
    mockInitTotalInc: vi.fn(),
    mockRevalidateContextMillResources: vi.fn(),
    mockResolveState: vi.fn(),
    mockTrackInitEvent: vi.fn(),
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
    })

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
})
