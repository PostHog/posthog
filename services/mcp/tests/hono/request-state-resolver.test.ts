import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockSessionStore, mockTokenStore } = vi.hoisted(() => ({
    mockSessionStore: new Map<string, unknown>(),
    mockTokenStore: new Map<string, unknown>(),
}))

vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({})),
    resolveFeatureFlagOverrides: vi.fn(() => ({})),
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
        RequestContext: vi.fn().mockImplementation(function (_redis, _env, props: { mcpSessionId?: string } = {}) {
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
                        getOrFetchGroupTypes: vi.fn(async () => undefined),
                        getEnvironmentPrompt: vi.fn(async () => undefined),
                        getAvailableFeatures: vi.fn(async () => undefined),
                    },
                })),
                safelyGetAnalyticsContext: vi.fn(async () => undefined),
                getDistinctId: vi.fn(async () => 'distinct-id'),
                setMcpContexts: vi.fn(),
            }
        }),
    }
})

import type { RedisLike } from '@/hono/cache/RedisCache'
import { RequestStateResolver } from '@/hono/request-state-resolver'
import { evaluateFeatureFlags, resolveFeatureFlagOverrides } from '@/lib/posthog/flags'
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
        ...overrides,
    }
}

function makeResolver(): RequestStateResolver {
    const catalog = {
        getFilteredTools: vi.fn(() => []),
    }
    return new RequestStateResolver(catalog as any, {} as RedisLike, {} as Env)
}

function makeResolverWithTools(toolNames: string[]): RequestStateResolver {
    const catalog = {
        getFilteredTools: vi.fn(() => toolNames.map((name) => ({ name }))),
    }
    return new RequestStateResolver(catalog as any, {} as RedisLike, {} as Env)
}

describe('RequestStateResolver MCP client contexts', () => {
    beforeEach(() => {
        mockSessionStore.clear()
        mockTokenStore.clear()
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

    it('auto-selects tools mode from the ChatGPT user-agent', async () => {
        // ChatGPT's clientInfo.name is generic; the surface only shows up in the
        // User-Agent. Guards the `userAgent: props.clientUserAgent` profile plumbing.
        const props = makeProps({ mcpClientName: undefined, clientUserAgent: 'openai-mcp/1.0.0 (ChatGPT)' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(false)
        expect(props.mode).toBe('tools')
    })

    it('defaults to cli mode when no client hints are present', async () => {
        const props = makeProps({
            mcpClientName: undefined,
            mcpClientVersion: undefined,
            mcpProtocolVersion: undefined,
        })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
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

    it('puts Claude web/desktop in single-exec when the render-ui flag is on', async () => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'mcp-render-ui': true })
        const props = makeProps({ mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(true)
        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('keeps Claude web/desktop in single-exec via the Claude-User user agent even when the render-ui flag is off', async () => {
        // Anthropic clients always run in CLI (single-exec) mode, so the
        // User-Agent-only path is single-exec regardless of the render-ui flag — the
        // flag only gates whether the `render-ui` tool itself is advertised.
        const props = makeProps({ mcpClientName: 'Claude Desktop', clientUserAgent: 'Claude-User' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(false)
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

    it('does not enable render-ui for Claude Code even when the flag is on', async () => {
        // Claude Code pools the same `mcp-render-ui` flag value as Claude web/desktop, but
        // it isn't an MCP Apps host — it can't mount the iframe. It must stay in single-exec
        // (it's a CLI client) while `renderUiEnabled` resolves to false, so the tool-executor
        // never advertises or accepts `render-ui` for it.
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'mcp-render-ui': true })
        const props = makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeCode' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(false)
        expect(result.useSingleExec).toBe(true)
        expect(result.toolFeatureFlags?.['mcp-render-ui']).toBe(true)
    })

    it('keeps render-ui on when a later pooled request flips the vendor header', async () => {
        // Regression: Anthropic pools MCP transports and sends `x-anthropic-client`
        // inconsistently within a session. The first request (Claude web/desktop, ClaudeAI)
        // resolves render-ui on; a later request on the same pooled session reports the
        // ClaudeCode vendor. The session-cached client context (first-observed
        // `mcpVendorClient` wins) keeps the UI-host classification — and with it the
        // advertised roster — stable, so the flip cannot retract a tool a cached
        // `tools/list` already advertised.
        vi.mocked(evaluateFeatureFlags)
            .mockResolvedValueOnce({ 'mcp-render-ui': true })
            .mockResolvedValueOnce({ 'mcp-render-ui': true })

        const first = await makeResolver().resolve(
            makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeAI' })
        )
        expect(first.renderUiEnabled).toBe(true)

        const flipped = await makeResolver().resolve(
            makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeCode' })
        )
        expect(flipped.clientProfile.vendorClient).toBe('ClaudeAI')
        expect(flipped.renderUiEnabled).toBe(true)
    })

    it('does not turn render-ui on when a Claude Code session later reports ClaudeAI (no leak)', async () => {
        // The mirror case: a session whose first-observed vendor is ClaudeCode must never
        // have `render-ui` enabled by a later ClaudeAI request sharing the pooled session
        // id — otherwise `render-ui` leaks into a non-UI host.
        vi.mocked(evaluateFeatureFlags)
            .mockResolvedValueOnce({ 'mcp-render-ui': true })
            .mockResolvedValueOnce({ 'mcp-render-ui': true })

        const first = await makeResolver().resolve(
            makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeCode' })
        )
        expect(first.renderUiEnabled).toBe(false)

        const flipped = await makeResolver().resolve(
            makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeAI' })
        )
        expect(flipped.clientProfile.vendorClient).toBe('ClaudeCode')
        expect(flipped.renderUiEnabled).toBe(false)
    })

    it('detects Claude web/desktop via the Claude-User user agent', async () => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'mcp-render-ui': true })
        const props = makeProps({ mcpClientName: 'Claude Desktop', clientUserAgent: 'Claude-User' })
        const result = await makeResolver().resolve(props)

        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('honors a dev/test flag override even when evaluation returns nothing', async () => {
        // Evaluation stays empty (analytics client disabled, as in local dev/evals);
        // the override seam is what flips the flag on.
        vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({ 'mcp-render-ui': true })
        const props = makeProps({ mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(true)
        expect(result.useSingleExec).toBe(true)
        expect(result.toolFeatureFlags?.['mcp-render-ui']).toBe(true)
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
})

describe('RequestStateResolver SQL schema-discovery flag', () => {
    beforeEach(() => {
        mockSessionStore.clear()
        mockTokenStore.clear()
        vi.mocked(evaluateFeatureFlags).mockResolvedValue({})
    })

    // The flag steers discovery instructions toward SQL but is prompt-only — it must NOT
    // remove read-data-warehouse-schema from the tool set. Guards against re-introducing
    // tool gating here; the tool stays advertised/callable whether the flag is on or off.
    it.each([true, false])('keeps read-data-warehouse-schema available when the flag is %s', async (flagOn) => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'mcp-sql-schema-discovery': flagOn })
        const resolver = makeResolverWithTools(['read-data-warehouse-schema', 'execute-sql'])

        const result = await resolver.resolve(makeProps())

        const names = result.allTools.map((t) => t.name)
        expect(names).toContain('read-data-warehouse-schema')
        expect(names).toContain('execute-sql')
    })
})
