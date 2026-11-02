import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
    mockSessionStore,
    mockTokenStore,
    mockApiKey,
    mockSessionScopedStores,
    mockRefreshTtlCalls,
    mockRedisFailures,
    mockPinned,
    mockGetApiKey,
    mockAnalyticsContext,
    mockDistinctId,
} = vi.hoisted(() => ({
    mockGetApiKey: vi.fn(),
    mockAnalyticsContext: { current: undefined as MCPAnalyticsContext | undefined },
    mockDistinctId: { current: 'distinct-id' },
    mockSessionStore: new Map<string, unknown>(),
    mockTokenStore: new Map<string, unknown>(),
    mockApiKey: {
        scopes: ['*'],
        scoped_teams: [],
        is_impersonated: undefined as boolean | undefined,
        suppress_analytics: undefined as boolean | undefined,
        mcp_allowed_tools: undefined as string[] | undefined,
    },
    mockSessionScopedStores: new Map<string, Map<string, unknown>>(),
    // Records the keys passed to every session-scoped refreshTtl call (only the
    // session cache refreshes, so any recorded call is a session refresh).
    mockRefreshTtlCalls: [] as string[][],
    mockRedisFailures: {
        contextError: undefined as Error | undefined,
        pinWriteGate: undefined as Promise<void> | undefined,
        legacyReadError: undefined as Error | undefined,
        contextReads: 0,
    },
    // The request-scoped context the last resolve handed to RequestContext.
    mockPinned: { last: undefined as { orgId?: string; projectId?: string; sessionScoped: boolean } | undefined },
}))

vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({ flags: {}, payloads: {} })),
    resolveFeatureFlagOverrides: vi.fn(() => ({})),
}))

vi.mock('@/hono/cache/McpSessionRedisStore', () => ({
    McpSessionRedisStore: class {
        async resolve(requestContext: Record<string, unknown>): Promise<Record<string, unknown>> {
            const keys = [
                'mcpClientName',
                'mcpClientVersion',
                'mcpProtocolVersion',
                'mcpConsumer',
                'mcpVendorClient',
                'mcpUiSupported',
            ]
            const resolved = Object.fromEntries(
                keys.map((key) => [key, mockSessionStore.get(key) ?? requestContext[key]])
            )
            for (const key of keys) {
                if (!mockSessionStore.has(key) && requestContext[key] !== undefined) {
                    mockSessionStore.set(key, requestContext[key])
                }
            }
            return resolved
        }
    },
}))

vi.mock('@/hono/request-context', async () => {
    const { StateLookupCache } = await import('@/lib/cache/StateLookupCache')
    type MockCache = {
        get: (key: string) => Promise<unknown>
        set: (key: string, value: unknown) => Promise<void>
        setMany: (entries: Record<string, unknown>) => Promise<void>
        delete: (key: string) => Promise<void>
        clear: () => Promise<void>
        refreshTtl: (keys: string[]) => Promise<void>
    }

    const makeCache = (store: Map<string, unknown>): MockCache => ({
        get: vi.fn(async (key: string) => store.get(key)),
        set: vi.fn(async (key: string, value: unknown) => {
            store.set(key, value)
        }),
        setMany: vi.fn(async (entries: Record<string, unknown>) => {
            if (store !== mockTokenStore) {
                await mockRedisFailures.pinWriteGate
            }
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
        refreshTtl: vi.fn(async (keys: string[]) => {
            mockRefreshTtlCalls.push(keys)
        }),
    })

    const sessionScopedStore = (mcpSessionId: string): Map<string, unknown> => {
        let store = mockSessionScopedStores.get(mcpSessionId)
        if (!store) {
            store = new Map<string, unknown>()
            mockSessionScopedStores.set(mcpSessionId, store)
        }
        return store
    }

    return {
        RequestContext: vi.fn().mockImplementation(function (...args: unknown[]) {
            const props = args[2] as RequestProperties
            return {
                tokenCache: { ...makeCache(mockTokenStore), scope: props.userHash },
                lookups: args[4] ?? new StateLookupCache(),
                sessionScopedCache: props.mcpSessionId ? makeCache(sessionScopedStore(props.mcpSessionId)) : undefined,
                legacySessionScopedCache: props.mcpSessionId
                    ? {
                          get: vi.fn(async () => {
                              if (mockRedisFailures.legacyReadError) {
                                  throw mockRedisFailures.legacyReadError
                              }
                              return undefined
                          }),
                      }
                    : undefined,
                getContext: vi.fn(async () => {
                    mockRedisFailures.contextReads += 1
                    if (mockRedisFailures.contextError) {
                        throw mockRedisFailures.contextError
                    }
                    return {
                        stateManager: {
                            setDefaultOrganizationAndProject: vi.fn(async () => {}),
                            getApiKey: mockGetApiKey,
                            getAiConsentGiven: vi.fn(async () => undefined),
                            getAvailableFeatures: vi.fn(async () => undefined),
                        },
                    }
                }),
                safelyGetAnalyticsContext: vi.fn(async () => mockAnalyticsContext.current),
                getDistinctId: vi.fn(async () => mockDistinctId.current),
                setMcpContexts: vi.fn(),
                setPinnedContext: vi.fn((pinned: typeof mockPinned.last) => {
                    mockPinned.last = pinned
                }),
            }
        }),
    }
})

import type { RedisLike } from '@/hono/cache/RedisCache'
import { MCP_EXEC_SKILLS_FEATURE_FLAG } from '@/hono/constants'
import { MCP_INTENT_PROMPT_FLAG } from '@/hono/intent-prompt'
import { MCP_INTERVIEW_RECRUITMENT_FLAG } from '@/hono/interview-recruitment'
import { RequestStateResolver } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { StateLookupCache } from '@/lib/cache/StateLookupCache'
import { MCP_NO_DATA_INSTALL_NOTICE_FLAG } from '@/lib/no-data-guard'
import type { MCPAnalyticsContext } from '@/lib/posthog/analytics'
import { evaluateFeatureFlags, resolveFeatureFlagOverrides } from '@/lib/posthog/flags'
import { parseRequestProperties, type RequestProperties } from '@/lib/request-properties'
import { TASKS_CONTEXT_TOOL_NAMES } from '@/tools/tasksContext'
import * as toolDefinitions from '@/tools/toolDefinitions'
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
        ...overrides,
    }
}

function makeResolver(): RequestStateResolver {
    return makeResolverWithCatalog().resolver
}

function makeResolverWithCatalog(): {
    resolver: RequestStateResolver
    getFilteredTools: ReturnType<typeof vi.fn>
} {
    const getFilteredTools = vi.fn(() => [])
    const catalog = {
        getFilteredTools,
    }
    return {
        resolver: new RequestStateResolver(catalog as any, {} as RedisLike, {} as Env),
        getFilteredTools,
    }
}

describe('RequestStateResolver MCP client contexts', () => {
    beforeEach(() => {
        mockSessionStore.clear()
        mockTokenStore.clear()
        mockSessionScopedStores.clear()
        mockRefreshTtlCalls.length = 0
        mockRedisFailures.contextError = undefined
        mockRedisFailures.pinWriteGate = undefined
        mockRedisFailures.legacyReadError = undefined
        mockRedisFailures.contextReads = 0
        mockPinned.last = undefined
        mockAnalyticsContext.current = undefined
        mockDistinctId.current = 'distinct-id'
        mockGetApiKey.mockReset().mockImplementation(async () => mockApiKey)
        mockApiKey.scopes = ['*']
        mockApiKey.is_impersonated = undefined
        mockApiKey.suppress_analytics = undefined
        mockApiKey.mcp_allowed_tools = undefined
    })

    it.each([
        { change: 'none', shared: true },
        { change: 'credential', shared: false },
        { change: 'distinct ID', shared: false },
        { change: 'project group', shared: false },
        { change: 'organization group', shared: false },
        { change: 'flag keys', shared: false },
        { change: 'flag order', shared: true },
        { change: 'next request', shared: false },
    ])('shares flag values and payloads only for matching inputs: $change', async ({ change, shared }) => {
        const requiredFlags = vi.spyOn(toolDefinitions, 'getRequiredFeatureFlags').mockReturnValue(['flag-a', 'flag-b'])
        const evaluate = vi
            .mocked(evaluateFeatureFlags)
            .mockClear()
            .mockResolvedValueOnce({
                flags: { [MCP_INTENT_PROMPT_FLAG]: 'first-variant' },
                payloads: { [MCP_INTENT_PROMPT_FLAG]: { prompt: 'First context prompt' } },
            })
            .mockResolvedValue({
                flags: { [MCP_INTENT_PROMPT_FLAG]: 'second-variant' },
                payloads: { [MCP_INTENT_PROMPT_FLAG]: { prompt: 'Second context prompt' } },
            })
        try {
            const lookups = new StateLookupCache()
            const resolver = makeResolver()
            mockAnalyticsContext.current = { organizationId: 'org-a', projectUuid: 'project-a' }
            const first = await resolver.resolve(makeProps(), lookups)
            if (change === 'distinct ID') {
                mockDistinctId.current = 'other-distinct-id'
            }
            if (change === 'project group') {
                mockAnalyticsContext.current.projectUuid = 'project-b'
            }
            if (change === 'organization group') {
                mockAnalyticsContext.current.organizationId = 'org-b'
            }
            if (change === 'flag keys') {
                requiredFlags.mockReturnValue(['other-flag'])
            }
            if (change === 'flag order') {
                requiredFlags.mockReturnValue(['flag-b', 'flag-a'])
            }
            const second = await resolver.resolve(
                makeProps(change === 'credential' ? { userHash: 'other-user', apiToken: 'phx_other' } : {}),
                change === 'next request' ? undefined : lookups
            )
            expect({
                calls: evaluate.mock.calls.length,
                first: { flag: first.toolFeatureFlags?.[MCP_INTENT_PROMPT_FLAG], prompt: first.intentPrompt },
                second: { flag: second.toolFeatureFlags?.[MCP_INTENT_PROMPT_FLAG], prompt: second.intentPrompt },
            }).toEqual({
                calls: shared ? 1 : 2,
                first: { flag: 'first-variant', prompt: 'First context prompt' },
                second: shared
                    ? { flag: 'first-variant', prompt: 'First context prompt' }
                    : { flag: 'second-variant', prompt: 'Second context prompt' },
            })
        } finally {
            requiredFlags.mockRestore()
            evaluate.mockReset().mockResolvedValue({ flags: {}, payloads: {} })
        }
    })

    it('retries a failed flag evaluation within the request', async () => {
        const evaluate = vi
            .mocked(evaluateFeatureFlags)
            .mockClear()
            .mockRejectedValueOnce(new Error('Synthetic flag failure'))
            .mockResolvedValue({
                flags: { [MCP_INTENT_PROMPT_FLAG]: true },
                payloads: { [MCP_INTENT_PROMPT_FLAG]: { prompt: 'Recovered prompt' } },
            })
        try {
            const lookups = new StateLookupCache()
            const resolver = makeResolver()
            const first = await resolver.resolve(makeProps(), lookups)
            const retry = await resolver.resolve(makeProps(), lookups)
            expect({ calls: evaluate.mock.calls.length, first: first.intentPrompt, retry: retry.intentPrompt }).toEqual(
                { calls: 2, first: undefined, retry: 'Recovered prompt' }
            )
        } finally {
            evaluate.mockReset().mockResolvedValue({ flags: {}, payloads: {} })
        }
    })

    it.each([true, false, undefined])(
        'passes token capture policy=%s to analytics despite caller headers',
        async (impersonated) => {
            mockApiKey.is_impersonated = impersonated
            mockApiKey.suppress_analytics = impersonated

            const props = parseRequestProperties(
                new Request('https://example.com/mcp?suppress_analytics=true', {
                    headers: {
                        Authorization: 'Bearer pha_test',
                        'x-posthog-suppress-analytics': 'true',
                        'x-posthog-task-origin': 'signals_scout',
                    },
                }),
                {}
            )
            const result = await makeResolver().resolve(props)

            expect(result.isImpersonated).toBe(impersonated === true)
            expect(result.suppressAnalytics).toBe(impersonated === true)
            expect(props.suppressAnalytics).toBe(impersonated === true)
        }
    )

    it('handles a Redis context failure while a pinned-context write is pending', async () => {
        let releasePinWrite!: () => void
        mockRedisFailures.pinWriteGate = new Promise<void>((resolve) => {
            releasePinWrite = resolve
        })
        mockRedisFailures.contextError = new Error('Command timed out')
        const unhandled: unknown[] = []
        const onUnhandled = (error: unknown): void => {
            unhandled.push(error)
        }
        process.on('unhandledRejection', onUnhandled)

        try {
            const pending = makeResolver().resolve(makeProps())
            await new Promise<void>((resolve) => setImmediate(resolve))
            expect(mockRedisFailures.contextReads).toBe(0)
            expect(unhandled).toEqual([])
            releasePinWrite()
            await expect(pending).rejects.toThrow('Command timed out')
            await new Promise<void>((resolve) => setImmediate(resolve))
            expect(unhandled).toEqual([])
        } finally {
            releasePinWrite()
            process.off('unhandledRejection', onUnhandled)
        }
    })

    it.each([
        ['a pinned request', { projectId: '1' }],
        ['a request without a pin', { projectId: undefined }],
    ])('fails %s when the legacy session store cannot be read', async (_label, pin) => {
        // Skipping the check would let a pre-upgrade session run tools against a silently reset selection.
        mockRedisFailures.legacyReadError = new Error('Command timed out')

        await expect(makeResolver().resolve(makeProps(pin))).rejects.toThrow('Command timed out')
        expect(mockRedisFailures.contextReads).toBe(0)
    })

    it.each([
        ['cli', false],
        ['cli', true],
        ['tools', false],
        ['tools', true],
    ] as const)('filters run-start tools in %s mode with sandbox=%s', async (mode, sandbox) => {
        if (sandbox) {
            mockApiKey.scopes.push('internal_run:read')
        }
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({
            flags: { 'tasks-mcp-agent-run-start': true, tasks: true },
            payloads: {},
        })
        const catalog = new ToolCatalog()
        await catalog.warmup()
        const resolver = new RequestStateResolver(catalog, {} as RedisLike, {} as Env)

        const result = await resolver.resolve(makeProps({ mode }))
        const names = result.allTools.map((tool) => tool.name)

        for (const name of ['tasks-run-create', 'tasks-create-and-run']) {
            expect(names.includes(name)).toBe(!sandbox)
        }
        expect(names).toContain('tasks-create')
    })

    it('stores client props, but not resolved mode, for a new MCP session', async () => {
        const props = makeProps()
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
        expect(result.requestContext).toMatchObject({
            mcpClientName: 'claude-code',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
            mode: 'cli',
        })
        expect(result.sessionContext).toMatchObject({
            mcpClientName: 'claude-code',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
        })
        expect(mockSessionStore.get('mcpClientName')).toBe('claude-code')
        expect(mockSessionStore.get('mcpClientVersion')).toBe('1.0')
        expect(mockSessionStore.get('mcpProtocolVersion')).toBe('2025-03-26')
        expect(mockSessionStore.get('mcpMode')).toBeUndefined()
    })

    it('does not store mode for a new MCP session when the mode was explicit', async () => {
        const props = makeProps({ mode: 'tools' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
        expect(result.requestContext.mode).toBe('tools')
        expect(mockSessionStore.get('mcpMode')).toBeUndefined()
    })

    it('uses cached session client props when request client detection would resolve differently', async () => {
        // Cursor pins tools mode at initialize; a later request self-reporting a
        // cli-defaulting client must not downgrade the session out of tools mode.
        await makeResolver().resolve(makeProps({ mcpClientName: 'cursor' }))

        const props = makeProps({ mcpClientName: 'claude-code' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
        expect(props.mcpClientName).toBe('claude-code')
        expect(result.requestContext.mcpClientName).toBe('claude-code')
        expect(result.sessionContext?.mcpClientName).toBe('cursor')
        expect(result.clientProfile.clientName).toBe('cursor')
    })

    it('auto-selects tools mode from a name-less Cursor user-agent', async () => {
        // Older Cursor builds omit clientInfo.name and identify only through the
        // User-Agent. Guards the `userAgent: props.clientUserAgent` profile plumbing.
        const props = makeProps({ mcpClientName: undefined, clientUserAgent: 'Cursor/3.1.15 (darwin arm64)' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
    })

    it('keeps the labeled ChatGPT user-agent on the cli default', async () => {
        const props = makeProps({ mcpClientName: undefined, clientUserAgent: 'openai-mcp/1.0.0 (ChatGPT)' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('defaults to cli mode when no client hints are present', async () => {
        const props = makeProps({
            mcpClientName: undefined,
            mcpClientVersion: undefined,
            mcpProtocolVersion: undefined,
        })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(result.renderUiEnabled).toBe(false)
        expect(props.mode).toBe('cli')
    })

    it('uses cached session client props for instruction capabilities without overwriting request props', async () => {
        await makeResolver().resolve(makeProps({ mcpClientName: 'codex' }))

        const props = makeProps({ mcpClientName: 'Claude Desktop' })
        const result = await makeResolver().resolve(props)

        expect(props.mcpClientName).toBe('Claude Desktop')
        expect(result.requestContext.mcpClientName).toBe('Claude Desktop')
        expect(result.sessionContext?.mcpClientName).toBe('codex')
        expect(result.clientProfile.clientName).toBe('codex')
        expect(result.clientProfile.capabilities.supportsInstructions).toBe(false)
    })

    it('uses explicit mode when cached session client props would resolve differently', async () => {
        await makeResolver().resolve(makeProps())

        const props = makeProps({ mode: 'tools' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
    })

    it('does not pin mode without an MCP session ID', async () => {
        const props = makeProps({ mcpSessionId: undefined })
        const result = await makeResolver().resolve(props)

        expect(props.mode).toBe('cli')
        expect(result.sessionContext).toBeNull()
        expect(result.requestContext.mcpClientName).toBe('claude-code')
        expect(mockSessionStore.get('mcpMode')).toBeUndefined()
    })

    it('uses cached vendor client when the live vendor header would resolve differently', async () => {
        await makeResolver().resolve(
            makeProps({
                mcpClientName: 'Anthropic/ClaudeAI',
                mcpVendorClient: 'ClaudeCode',
            })
        )
        expect(mockSessionStore.get('mcpVendorClient')).toBe('ClaudeCode')

        const pooled = makeProps({
            mcpClientName: 'Anthropic/ClaudeAI',
            mcpVendorClient: 'ClaudeAI',
        })
        const result = await makeResolver().resolve(pooled)

        expect(result.useSingleExec).toBe(true)
        expect(pooled.mode).toBe('cli')
        expect(pooled.mcpVendorClient).toBe('ClaudeAI')
        expect(result.requestContext.mcpVendorClient).toBe('ClaudeAI')
        expect(result.sessionContext?.mcpVendorClient).toBe('ClaudeCode')
        expect(result.clientProfile.vendorClient).toBe('ClaudeCode')
    })

    it('captures vendor client from a later request when initialize omitted the header', async () => {
        await makeResolver().resolve(
            makeProps({
                mcpClientName: 'Anthropic/ClaudeAI',
                mcpVendorClient: undefined,
            })
        )
        expect(mockSessionStore.get('mcpVendorClient')).toBeUndefined()

        const pooled = makeProps({
            mcpClientName: 'Anthropic/ClaudeAI',
            mcpVendorClient: 'ClaudeCode',
        })
        const result = await makeResolver().resolve(pooled)

        expect(result.useSingleExec).toBe(true)
        expect(pooled.mode).toBe('cli')
        expect(result.requestContext.mcpVendorClient).toBe('ClaudeCode')
        expect(result.sessionContext?.mcpVendorClient).toBe('ClaudeCode')
        expect(mockSessionStore.get('mcpVendorClient')).toBe('ClaudeCode')
    })

    it.each([
        { mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI' },
        { mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'Cowork' },
        { mcpClientName: 'example-client', mcpUiSupported: true },
        { mcpClientName: 'openai-mcp' },
        { mcpClientName: undefined, clientUserAgent: 'openai-mcp/1.0.0' },
    ])('puts UI host %j in single-exec and enables render-ui', async (clientProps) => {
        const props = makeProps(clientProps)
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(true)
        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('puts header-less Claude.ai (pooled Anthropic/* name + Claude-User UA, no vendor header) in single-exec', async () => {
        // The production gap: Claude.ai web/desktop sessions that omit the
        // x-anthropic-client header and report only clientInfo.name "Anthropic/ClaudeAI"
        // with a Claude-User user-agent previously fell into tools mode.
        const props = makeProps({
            mcpClientName: 'Anthropic/ClaudeAI',
            mcpVendorClient: undefined,
            clientUserAgent: 'Claude-User',
        })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it.each([
        { mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeCode' },
        { mcpClientName: 'example-client' },
        { mcpClientName: 'codex-mcp-client', clientUserAgent: 'codex-mcp-client/0.165.0' },
        { mcpClientName: 'ChatGPT' },
        { mcpClientName: 'codex', mcpUiSupported: false },
        { mcpClientName: undefined, clientUserAgent: 'openai-mcp/1.0.0', mcpUiSupported: false },
        { mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI', mcpUiSupported: false },
    ])('does not enable render-ui without UI support for %j', async (clientProps) => {
        const props = makeProps(clientProps)
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(false)
        expect(result.useSingleExec).toBe(true)
    })

    it.each([
        { cached: true, live: undefined, expected: true },
        { cached: true, live: false, expected: false },
        { cached: false, live: true, expected: true },
    ])('resolves UI support from the live declaration before the legacy session: %j', async (testCase) => {
        await makeResolver().resolve(makeProps({ mcpClientName: 'example-client', mcpUiSupported: testCase.cached }))

        const result = await makeResolver().resolve(makeProps({ mcpUiSupported: testCase.live }))

        expect(result.renderUiEnabled).toBe(testCase.expected)
    })

    it('detects Claude web/desktop via the Claude-User user agent and enables render-ui', async () => {
        const props = makeProps({ mcpClientName: 'Claude Desktop', clientUserAgent: 'Claude-User' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(true)
        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it.each([
        MCP_EXEC_SKILLS_FEATURE_FLAG,
        MCP_INTERVIEW_RECRUITMENT_FLAG,
        MCP_INTENT_PROMPT_FLAG,
        MCP_NO_DATA_INSTALL_NOTICE_FLAG,
    ])('evaluates %s even though no generated tool declares it', async (flag) => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ flags: { [flag]: true }, payloads: {} })

        const result = await makeResolver().resolve(makeProps())

        expect(evaluateFeatureFlags).toHaveBeenCalledWith(expect.arrayContaining([flag]), 'distinct-id', undefined)
        expect(result.toolFeatureFlags?.[flag]).toBe(true)
    })

    // Unknown must stay unknown: the no-data notice only fires on an explicit false.
    it.each([
        [{ projectHasData: false }, false],
        [{ projectHasData: true }, true],
        [undefined, undefined],
    ])('carries the analytics context and its ingestion state %j', async (analyticsContext, expectedHasData) => {
        mockAnalyticsContext.current = analyticsContext

        const result = await makeResolver().resolve(makeProps())

        expect(result.projectHasData).toBe(expectedHasData)
        expect(result.analyticsContext).toBe(mockAnalyticsContext.current)
    })

    it.each([
        { taskId: 'test-task' },
        { taskOriginProduct: 'signals_scout' },
        { taskOriginProduct: 'research' },
        { scopes: ['internal_run:read'] },
        { oauthClientId: 'jpSRPhGBBbDGpKprit9bgJEuo6oUTa8ULymqf8PE' },
        { oauthClientId: 'N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu' },
        { oauthClientId: 'jpSRPhGBBbDGpKprit9bgJEuo6oUTa8ULymqf8PE', cold: true },
        { oauthClientId: 'N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu', cold: true },
        { oauthClientId: 'https://posthog.com/.well-known/oauth/webmcp/client-metadata.json' },
        { mcpConsumer: 'posthog-cli' },
    ])('enforces recruitment eligibility even when the flag is forced on: %j', async (input) => {
        if (input.scopes) {
            mockApiKey.scopes = input.scopes
        }
        if (input.oauthClientId) {
            if (input.cold) {
                mockGetApiKey.mockImplementationOnce(async () => {
                    await new Promise<void>((resolve) => setImmediate(resolve))
                    mockTokenStore.set('oauthClientId', input.oauthClientId)
                    mockTokenStore.set('clientName', 'Synthetic first-party application')
                    return mockApiKey
                })
            } else {
                mockTokenStore.set('oauthClientId', input.oauthClientId)
            }
        }
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({
            flags: {},
            payloads: {
                [MCP_INTERVIEW_RECRUITMENT_FLAG]: {
                    message: 'Synthetic interview',
                    booking_url: 'https://example.com/book',
                },
            },
        })
        vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({ [MCP_INTERVIEW_RECRUITMENT_FLAG]: true })
        const result = await makeResolver().resolve(makeProps(input))
        if (input.oauthClientId) {
            expect(result.oauthClientId).toBe(input.oauthClientId)
        }
        expect(result.interviewRecruitmentConfig).toBeUndefined()
        expect(result.interviewRecruitmentUnavailableReason).toBe(
            input.oauthClientId || input.mcpConsumer ? 'surface_excluded' : input.scopes ? 'internal_run' : 'task_bound'
        )
    })

    it.each([
        {
            payload: { message: 'Synthetic interview', booking_url: 'https://example.com/book' },
            expected: {
                campaign_id: 'mcp-research',
                booking_url: 'https://example.com/book',
                min_completed_tool_calls: 3,
                min_session_age_seconds: 120,
            },
        },
        {
            payload: { message: 'A new invitation', booking_url: 'https://example.com/book' },
            expected: { message: 'A new invitation', booking_url: 'https://example.com/book' },
        },
        { payload: { message: '' }, expected: undefined },
        { payload: { booking_url: 'javascript:alert(1)' }, expected: undefined },
        { payload: { booking_url: 'http://example.com/book' }, expected: undefined },
        { payload: { booking_url: 'not a URL' }, expected: undefined },
        { payload: 'invalid', expected: undefined },
        { payload: undefined, expected: undefined },
        { payload: null, expected: undefined },
        { payload: {}, expected: undefined },
        { payload: { message: 'Synthetic interview' }, expected: undefined },
        { payload: { booking_url: 'https://example.com/book' }, expected: undefined },
        {
            value: 'other-study',
            payload: { message: 'Another interview', booking_url: 'https://example.com/other' },
            expected: {
                campaign_id: 'other-study',
                booking_url: 'https://example.com/other',
                min_completed_tool_calls: 3,
                min_session_age_seconds: 120,
            },
        },
        { value: 'other-study', payload: undefined, expected: undefined },
        { value: 'other-study', payload: {}, expected: undefined },
        { value: 'other-study', payload: { message: 'Another interview' }, expected: undefined },
        { value: 'other-study', payload: { booking_url: 'https://example.com/other' }, expected: undefined },
        { value: '', payload: {}, expected: undefined },
        { value: false, payload: {}, expected: undefined },
    ])(
        'validates recruitment configuration from the flag payload: $payload',
        async ({ value = true, payload, expected }) => {
            vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({
                flags: { [MCP_INTERVIEW_RECRUITMENT_FLAG]: value },
                payloads: { [MCP_INTERVIEW_RECRUITMENT_FLAG]: payload },
            })
            const state = await makeResolver().resolve(makeProps())
            if (expected) {
                expect(state.interviewRecruitmentConfig).toMatchObject(expected)
                expect(state.interviewRecruitmentUnavailableReason).toBeUndefined()
            } else {
                expect(state.interviewRecruitmentConfig).toBeUndefined()
                expect(state.interviewRecruitmentUnavailableReason).toBe(
                    value === false ? 'flag_disabled' : 'invalid_configuration'
                )
            }
        }
    )

    it.each([
        { value: true, enabled: true },
        { value: 'test-1', enabled: true },
        { value: false, enabled: false },
        { value: undefined, enabled: false },
        { value: '', enabled: false },
        { value: true, missingPayload: true, enabled: false },
        { value: true, payload: { prompt: ' ' }, enabled: false },
        { value: true, payload: { prompt: 'x'.repeat(2001) }, enabled: false },
        { value: true, impersonated: true, enabled: false },
        { value: true, suppressed: true, enabled: false },
        { value: true, consumer: 'posthog-cli', enabled: false },
    ])('resolves the intent prompt only for an eligible configured request: %j', async (input) => {
        const prompt = {
            prompt: 'State the task objective before the tool action. Omit identifying details.',
        }
        mockApiKey.is_impersonated = input.impersonated
        mockApiKey.suppress_analytics = input.suppressed
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({
            flags: { [MCP_INTENT_PROMPT_FLAG]: input.value },
            payloads: {
                [MCP_INTENT_PROMPT_FLAG]: input.missingPayload ? undefined : { ...prompt, ...input.payload },
            },
        })
        const state = await makeResolver().resolve(makeProps({ mcpConsumer: input.consumer }))

        expect(state.intentPrompt).toEqual(input.enabled ? prompt.prompt : undefined)
    })

    it('honors a dev/test flag override even when evaluation returns nothing', async () => {
        const evaluate = vi.mocked(evaluateFeatureFlags).mockClear()
        vi.mocked(resolveFeatureFlagOverrides)
            .mockReturnValueOnce({ 'dev-forced-flag': false })
            .mockReturnValueOnce({ 'dev-forced-flag': true })
        const lookups = new StateLookupCache()
        const resolver = makeResolver()
        const first = await resolver.resolve(makeProps(), lookups)
        const second = await resolver.resolve(makeProps(), lookups)

        expect({
            calls: evaluate.mock.calls.length,
            overrides: [first.toolFeatureFlags?.['dev-forced-flag'], second.toolFeatureFlags?.['dev-forced-flag']],
        }).toEqual({ calls: 1, overrides: [false, true] })
    })

    it.each([
        { mode: 'development', override: undefined, payload: 'valid', enabled: false },
        { mode: 'development', override: true, payload: undefined, enabled: false },
        { mode: 'development', override: true, payload: '{', enabled: false },
        { mode: 'development', override: true, payload: '{}', enabled: false },
        { mode: 'development', override: true, payload: 'valid', enabled: true },
        { mode: 'development', override: 'other-study', payload: 'valid', enabled: true },
        { mode: 'test', override: true, payload: 'valid', enabled: true },
        { mode: 'production', override: true, payload: 'valid', enabled: false },
    ])('requires explicit local recruitment opt-in and payload: %j', async ({ mode, override, payload, enabled }) => {
        vi.stubEnv('POSTHOG_API_BASE_URL', 'http://localhost:8000')
        vi.stubEnv('NODE_ENV', mode)
        vi.stubEnv(
            'MCP_INTERVIEW_RECRUITMENT_PAYLOAD',
            payload === 'valid'
                ? JSON.stringify({ message: 'Synthetic local interview', booking_url: 'https://example.com/book' })
                : payload
        )
        try {
            if (override) {
                vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({
                    [MCP_INTERVIEW_RECRUITMENT_FLAG]: override,
                })
            }
            const result = await makeResolver().resolve(makeProps())
            if (enabled) {
                expect(result.interviewRecruitmentConfig).toMatchObject({
                    campaign_id: typeof override === 'string' ? override : 'mcp-research',
                    message: 'Synthetic local interview',
                    booking_url: 'https://example.com/book',
                })
            } else {
                expect(result.interviewRecruitmentConfig).toBeUndefined()
            }
        } finally {
            vi.unstubAllEnvs()
        }
    })

    describe('pinned project/org context', () => {
        const simulateSwitch = (mcpSessionId: string, projectId: string, orgId?: string): void => {
            const store = mockSessionScopedStores.get(mcpSessionId)
            store?.set('activeProjectId', projectId)
            if (orgId) {
                store?.set('activeOrgId', orgId)
            }
        }

        it('does not revert an in-session switch-project when the same pin is resent', async () => {
            // Pinning clients resend `?project_id=` on every request. The first
            // request establishes the pin; a later switch-project selects a new
            // active project that the resent pin must not clobber.
            await makeResolver().resolve(makeProps({ projectId: '1' }))
            expect(mockPinned.last?.projectId).toBe('1')

            simulateSwitch('mcp-session-1', '2')

            await makeResolver().resolve(makeProps({ projectId: '1' }))
            expect(mockPinned.last?.projectId).toBe('2')
        })

        it('re-applies a changed pin and discards the recorded switch', async () => {
            await makeResolver().resolve(makeProps({ projectId: '1' }))
            simulateSwitch('mcp-session-1', '2')

            await makeResolver().resolve(makeProps({ projectId: '9' }))
            expect(mockPinned.last?.projectId).toBe('9')
            expect(mockSessionScopedStores.get('mcp-session-1')?.get('activeProjectId')).toBeUndefined()
        })

        it('reverts org and project together when only the project pin changes after a cross-org switch', async () => {
            // A both-pins client that switch-projects across orgs, then changes only
            // its project pin, must not keep the switched org: pin is one context, so
            // any changed pin value reverts both fields. Otherwise org-scoped tools
            // stay on the switched org while project-scoped tools use the new pin.
            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '1' }))
            simulateSwitch('mcp-session-1', '2', 'org-2')

            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '9' }))
            expect(mockPinned.last).toMatchObject({ orgId: 'org-1', projectId: '9' })
        })

        it('applies the pin on every request without an MCP session id', async () => {
            // No session means no cross-request continuity, so the pin wins each
            // request and the switch tools must refuse instead of reporting success.
            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: undefined }))
            expect(mockPinned.last).toMatchObject({ projectId: '1', sessionScoped: false })
        })

        it.each([
            ['with an MCP session', 'mcp-session-1'],
            ['without an MCP session', undefined],
        ])('never writes the pin into the shared token cache %s', async (_label, mcpSessionId) => {
            // The token cache is shared by every session on the credential. A pin
            // written there reverts a switch-project and leaks into other sessions.
            mockTokenStore.set('projectId', '2')
            mockTokenStore.set('orgId', 'org-2')

            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '1', mcpSessionId }))

            expect(mockTokenStore.get('projectId')).toBe('2')
            expect(mockTokenStore.get('orgId')).toBe('org-2')
            expect(mockPinned.last).toMatchObject({ orgId: 'org-1', projectId: '1' })
        })

        it('keeps concurrent sessions with different pins on one token isolated', async () => {
            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: 'session-a' }))
            await makeResolver().resolve(makeProps({ projectId: '2', mcpSessionId: 'session-b' }))
            expect(mockPinned.last?.projectId).toBe('2')

            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: 'session-a' }))
            expect(mockPinned.last?.projectId).toBe('1')
        })

        it.each([
            ['pinned', '1'],
            ['unpinned', undefined],
        ])('renews the session-scoped keys TTL on every %s request', async (_label, projectId) => {
            // The keys carry a write-based TTL; without a per-request refresh a
            // switch recorded early in a long session expires first, reads back as
            // a changed pin, and the pin silently wins again.
            await makeResolver().resolve(makeProps({ projectId }))

            expect(mockRefreshTtlCalls).toContainEqual(
                expect.arrayContaining([
                    'appliedPinOrgId',
                    'appliedPinProjectId',
                    'activeOrgId',
                    'activeProjectId',
                    'defaultContext',
                    'defaultProjectId',
                ])
            )
        })
    })

    it('captures consumer from a later request when initialize omitted the header', async () => {
        await makeResolver().resolve(
            makeProps({
                mcpClientName: 'Claude Desktop',
                mcpConsumer: undefined,
            })
        )
        expect(mockSessionStore.get('mcpConsumer')).toBeUndefined()

        const posthogCode = makeProps({
            mcpClientName: 'Claude Desktop',
            mcpConsumer: 'posthog-code',
        })
        const result = await makeResolver().resolve(posthogCode)

        expect(result.useSingleExec).toBe(true)
        expect(posthogCode.mode).toBe('cli')
        expect(result.requestContext.mcpConsumer).toBe('posthog-code')
        expect(result.sessionContext?.mcpConsumer).toBe('posthog-code')
        expect(mockSessionStore.get('mcpConsumer')).toBe('posthog-code')
    })

    it.each([
        ['a Desktop task', { taskOriginProduct: undefined }, true],
        ['a support reply task', { taskOriginProduct: 'support_reply' }, true],
        // Scout sandboxes mount gateway servers directly as `mcp__<server>__<tool>`; a second
        // `<slug>__<tool>` spelling inside exec resolves for a member but not for the service
        // account, so skills learned interactively fail on the schedule.
        ['a scout run', { taskOriginProduct: 'signals_scout' }, false],
    ] as const)('surfaces gateway tools through exec for %s', async (_label, overrides, enabled) => {
        vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({ 'mcp-gateway': true })

        const result = await makeResolver().resolve(makeProps({ mcpConsumer: 'posthog-code', ...overrides }))

        expect(result.useSingleExec).toBe(true)
        expect(result.gatewayToolsEnabled).toBe(enabled)
    })

    it('keeps Store connections on individual tools without nested connectors', async () => {
        vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({ 'mcp-gateway': true })
        const props = parseRequestProperties(
            new Request('https://example.com/mcp?mode=cli', {
                headers: {
                    Authorization: 'Bearer phx_test',
                    'x-posthog-mcp-store': 'true',
                    'x-posthog-mcp-mode': 'cli',
                },
            }),
            {}
        )
        const result = await makeResolver().resolve(props)
        expect(result.useSingleExec).toBe(false)
        expect(result.gatewayToolsEnabled).toBe(false)
        expect(result.viaMcpStore).toBe(true)
    })

    it('carries connected-tool restrictions to execution', async () => {
        const filters = {
            tools: ['linear__create_issue'],
            features: ['dashboards'],
            excludeTools: ['linear__delete_issue'],
        }
        const result = await makeResolver().resolve(makeProps(filters))
        expect(result.gatewayToolFilter).toMatchObject({ tools: filters.tools, features: filters.features })
        expect(result.gatewayToolFilter?.excludeTools).toContain('linear__delete_issue')
    })

    it.each([
        ['PostHog Code task', { mcpConsumer: 'posthog-code', taskId: 'task-1' }, false],
        ['PostHog Code without a task', { mcpConsumer: 'posthog-code', taskId: undefined }, true],
        ['non-PostHog Code task', { mcpConsumer: 'other', taskId: 'task-1' }, true],
    ] as const)('advertises task artifacts and comments for %s', async (_label, overrides, excluded) => {
        const { resolver, getFilteredTools } = makeResolverWithCatalog()

        await resolver.resolve(makeProps(overrides))

        const options = getFilteredTools.mock.calls[0]?.[0]
        expect(options?.excludeTools).toEqual(
            excluded
                ? expect.arrayContaining([...TASKS_CONTEXT_TOOL_NAMES])
                : expect.not.arrayContaining([...TASKS_CONTEXT_TOOL_NAMES])
        )
    })

    // A gated hint outside the held set would send the agent after a tool it can never get.
    it('limits the roster and the gated hints to the held tool set', async () => {
        mockApiKey.scopes = ['project:read']
        mockApiKey.mcp_allowed_tools = ['docs-search', 'dashboards-get-all']
        const catalog = new ToolCatalog()
        await catalog.warmup()
        const resolver = new RequestStateResolver(catalog, {} as RedisLike, {} as Env)

        const result = await resolver.resolve(makeProps({ mode: 'cli' }))

        expect(result.allTools.map((tool) => tool.name)).toEqual(['docs-search'])
        expect(result.scopeGatedTools.map((tool) => tool.name)).toEqual(['dashboards-get-all'])
        expect(result.flagGatedTools).toEqual([])
    })

    it('merges request excludeTools into catalog filter options', async () => {
        const { resolver, getFilteredTools } = makeResolverWithCatalog()

        await resolver.resolve(makeProps({ excludeTools: ['docs-search'] }))

        expect(getFilteredTools.mock.calls[0]?.[0]?.excludeTools).toEqual(expect.arrayContaining(['docs-search']))
    })
})
