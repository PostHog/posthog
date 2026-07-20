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

function makeRequest(method: string): Request {
    return new Request('https://mcp.test/mcp', {
        body: JSON.stringify({
            id: 1,
            jsonrpc: '2.0',
            method,
            params:
                method === 'initialize'
                    ? {
                          capabilities: {},
                          clientInfo: { name: 'test-client', version: '1.0.0' },
                          protocolVersion: LATEST_PROTOCOL_VERSION,
                      }
                    : {},
        }),
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
    })
}

describe('McpDispatcher init error accounting', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockBuildInstructions.mockResolvedValue('')
        mockResolveState.mockResolvedValue({ distinctId: 'test-distinct-id' })
        mockTrackInitEvent.mockResolvedValue(undefined)
        mockRevalidateContextMillResources.mockResolvedValue(undefined)
    })

    it('counts an initialize handshake as errored when state resolution fails', async () => {
        const resolutionError = new Error('django auth is down')
        mockResolveState.mockRejectedValueOnce(resolutionError)

        const dispatcher = new McpDispatcher({} as any, createMockRedis())

        await expect(dispatcher.handleRequest(makeRequest('initialize'), makeProps())).rejects.toBe(resolutionError)
        expect(mockInitTotalInc).toHaveBeenCalledWith({ status: 'error' })
    })

    it('does not count non-initialize requests when state resolution fails', async () => {
        mockResolveState.mockRejectedValueOnce(new Error('django auth is down'))

        const dispatcher = new McpDispatcher({} as any, createMockRedis())

        await expect(dispatcher.handleRequest(makeRequest('tools/list'), makeProps())).rejects.toThrow()
        expect(mockInitTotalInc).not.toHaveBeenCalled()
    })

    it('counts a successful initialize handshake once', async () => {
        const dispatcher = new McpDispatcher({} as any, createMockRedis())

        const response = await dispatcher.handleRequest(makeRequest('initialize'), makeProps())

        expect(response.status).toBe(200)
        expect(mockInitTotalInc).toHaveBeenCalledTimes(1)
        expect(mockInitTotalInc).toHaveBeenCalledWith({ status: 'success' })
    })
})
