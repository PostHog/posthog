import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockSessionStore, mockTokenStore } = vi.hoisted(() => ({
    mockSessionStore: new Map<string, unknown>(),
    mockTokenStore: new Map<string, unknown>(),
}))

vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({})),
}))

vi.mock('@/hono/request-context', () => {
    type MockCache = {
        get: (key: string) => Promise<unknown>
        set: (key: string, value: unknown) => Promise<void>
        setMany: (entries: Record<string, unknown>) => Promise<void>
        delete: (key: string) => Promise<void>
        clear: () => Promise<void>
    }

    const makeCache = (store: Map<string, unknown>): MockCache => ({
        get: vi.fn(async (key: string) => store.get(key)),
        set: vi.fn(async (key: string, value: unknown) => {
            store.set(key, value)
        }),
        setMany: vi.fn(async (entries: Record<string, unknown>) => {
            for (const [key, value] of Object.entries(entries)) {
                if (value !== undefined) {
                    store.set(key, value)
                }
            }
        }),
        delete: vi.fn(async (key: string) => {
            store.delete(key)
        }),
        clear: vi.fn(async () => {
            store.clear()
        }),
    })

    return {
        RequestContext: vi.fn().mockImplementation((_redis, _env, props: { mcpSessionId?: string } = {}) => {
            const sessionCache = makeCache(mockSessionStore)
            return {
                tokenCache: makeCache(mockTokenStore),
                get sessionCache() {
                    if (!props.mcpSessionId) {
                        throw new Error('Session ID is required to use the session cache')
                    }
                    return sessionCache
                },
                getContext: vi.fn(async () => ({
                    stateManager: {
                        setDefaultOrganizationAndProject: vi.fn(async () => {}),
                        getApiKey: vi.fn(async () => ({ scopes: ['*'], scoped_teams: [] })),
                        getAiConsentGiven: vi.fn(async () => undefined),
                    },
                })),
                getAnalyticsContextSafe: vi.fn(async () => undefined),
                getDistinctId: vi.fn(async () => 'distinct-id'),
            }
        }),
    }
})

import type { RedisLike } from '@/hono/cache/RedisCache'
import { RequestStateResolver } from '@/hono/request-state-resolver'
import type { RequestProperties } from '@/lib/request-properties'
import type { Env } from '@/tools/types'

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        apiToken: 'phx_test',
        userHash: 'test-user',
        mcpSessionId: 'mcp-session-1',
        mcpClientName: 'claude-code',
        mcpClientVersion: '1.0',
        mcpProtocolVersion: '2025-03-26',
        projectId: '1',
        requestStartTime: Date.now(),
        transport: 'streamable-http',
        version: 1,
        ...overrides,
    }
}

function makeResolver(): RequestStateResolver {
    const catalog = {
        getFilteredTools: vi.fn(() => []),
    }
    return new RequestStateResolver(catalog as any, {} as RedisLike, {} as Env)
}

describe('RequestStateResolver MCP mode pinning', () => {
    beforeEach(() => {
        mockSessionStore.clear()
        mockTokenStore.clear()
    })

    it('stores the resolved mode for a new MCP session', async () => {
        const props = makeProps()
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
        expect(mockSessionStore.get('mcpMode')).toBe('cli')
    })

    it('does not store mode for a new MCP session when the mode was explicit', async () => {
        const props = makeProps({ mode: 'tools' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
        expect(mockSessionStore.get('mcpMode')).toBeUndefined()
    })

    it('uses cached session mode when client detection would resolve differently', async () => {
        await makeResolver().resolve(makeProps())

        const props = makeProps({ mcpClientName: 'Claude Desktop' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('uses explicit mode when an existing MCP session cached a different mode', async () => {
        await makeResolver().resolve(makeProps())

        const props = makeProps({ mode: 'tools' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
    })

    it('does not pin mode without an MCP session ID', async () => {
        const props = makeProps({ mcpSessionId: undefined })
        await makeResolver().resolve(props)

        expect(props.mode).toBe('cli')
        expect(mockSessionStore.get('mcpMode')).toBeUndefined()
    })
})
