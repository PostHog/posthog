import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockSessionStore, mockTokenStore, mockSessionScopedStores, mockRefreshTtlCalls } = vi.hoisted(() => ({
    mockSessionStore: new Map<string, unknown>(),
    mockTokenStore: new Map<string, unknown>(),
    mockSessionScopedStores: new Map<string, Map<string, unknown>>(),
    // Records the keys passed to every session-scoped refreshTtl call (only the
    // session cache refreshes, so any recorded call is a session refresh).
    mockRefreshTtlCalls: [] as string[][],
}))

vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({})),
    resolveFeatureFlagOverrides: vi.fn(() => ({})),
}))

vi.mock('@/hono/cache/McpSessionRedisStore', () => ({
    McpSessionRedisStore: class {
        async resolve(requestContext: Record<string, unknown>): Promise<Record<string, unknown>> {
            const keys = ['mcpClientName', 'mcpClientVersion', 'mcpProtocolVersion', 'mcpConsumer', 'mcpVendorClient']
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

vi.mock('@/hono/request-context', () => {
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
            const props = args[2] as { mcpSessionId?: string }
            return {
                tokenCache: makeCache(mockTokenStore),
                sessionScopedCache: props.mcpSessionId ? makeCache(sessionScopedStore(props.mcpSessionId)) : undefined,
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
import { resolveFeatureFlagOverrides } from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import { TASKS_CONTEXT_TOOL_NAMES } from '@/tools/tasksContext'
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

    it('puts Claude web/desktop in single-exec and enables render-ui', async () => {
        const props = makeProps({ mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI' })
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

    it('does not enable render-ui for Claude Code', async () => {
        // Claude Code is a single-exec CLI client but not an MCP Apps host — it can't
        // mount the iframe. It must stay in single-exec while `renderUiEnabled` resolves
        // to false, so the tool-executor never advertises or accepts `render-ui` for it.
        const props = makeProps({ mcpClientName: 'Anthropic/ClaudeAI', mcpVendorClient: 'ClaudeCode' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(false)
        expect(result.useSingleExec).toBe(true)
    })

    it('detects Claude web/desktop via the Claude-User user agent and enables render-ui', async () => {
        const props = makeProps({ mcpClientName: 'Claude Desktop', clientUserAgent: 'Claude-User' })
        const result = await makeResolver().resolve(props)

        expect(result.renderUiEnabled).toBe(true)
        expect(result.useSingleExec).toBe(true)
        expect(props.mode).toBe('cli')
    })

    it('honors a dev/test flag override even when evaluation returns nothing', async () => {
        // Evaluation stays empty (analytics client disabled, as in local dev/evals);
        // the override seam is what flips a tool flag on so it reaches the tool layer.
        vi.mocked(resolveFeatureFlagOverrides).mockReturnValueOnce({ 'dev-forced-flag': true })
        const props = makeProps({ mcpClientName: 'Claude Desktop', mcpVendorClient: 'ClaudeAI' })
        const result = await makeResolver().resolve(props)

        expect(result.toolFeatureFlags?.['dev-forced-flag']).toBe(true)
    })

    describe('pinned project/org context', () => {
        // What the switch-project handler does: write the token cache and record
        // the switch on the session (Context.setSessionActiveContext).
        const simulateSwitch = (mcpSessionId: string, projectId: string): void => {
            mockTokenStore.set('projectId', projectId)
            mockSessionScopedStores.get(mcpSessionId)?.set('activeProjectId', projectId)
        }

        it('does not revert an in-session switch-project when the same pin is resent', async () => {
            // Pinning clients resend `?project_id=` on every request. The first
            // request establishes the pin; a later switch-project selects a new
            // active project that the resent pin must not clobber.
            await makeResolver().resolve(makeProps({ projectId: '1' }))
            expect(mockTokenStore.get('projectId')).toBe('1')

            simulateSwitch('mcp-session-1', '2')

            await makeResolver().resolve(makeProps({ projectId: '1' }))
            expect(mockTokenStore.get('projectId')).toBe('2')
        })

        it('re-applies a changed pin and discards the recorded switch', async () => {
            await makeResolver().resolve(makeProps({ projectId: '1' }))
            simulateSwitch('mcp-session-1', '2')

            await makeResolver().resolve(makeProps({ projectId: '9' }))
            expect(mockTokenStore.get('projectId')).toBe('9')
            expect(mockSessionScopedStores.get('mcp-session-1')?.get('activeProjectId')).toBeUndefined()
        })

        it('reverts org and project together when only the project pin changes after a cross-org switch', async () => {
            // A both-pins client that switch-projects across orgs, then changes only
            // its project pin, must not keep the switched org: pin is one context, so
            // any changed pin value reverts both fields. Otherwise org-scoped tools
            // stay on the switched org while project-scoped tools use the new pin.
            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '1' }))

            // A cross-org switch-project records both fields on the session and the token cache.
            mockTokenStore.set('orgId', 'org-2')
            mockTokenStore.set('projectId', '2')
            mockSessionScopedStores.get('mcp-session-1')?.set('activeOrgId', 'org-2')
            mockSessionScopedStores.get('mcp-session-1')?.set('activeProjectId', '2')

            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '9' }))
            expect(mockTokenStore.get('orgId')).toBe('org-1')
            expect(mockTokenStore.get('projectId')).toBe('9')
        })

        it.each([
            {
                label: 'discards a switch that left it',
                switchedOrg: 'org-2',
                expectedOrg: 'org-1',
                expectedProject: '1',
            },
            {
                label: 'keeps a switch that stayed inside it',
                switchedOrg: 'org-1',
                expectedOrg: 'org-1',
                expectedProject: '2',
            },
        ])('a resent organization pin $label', async ({ switchedOrg, expectedOrg, expectedProject }) => {
            // An organization pin is a hard lock — switchToolsToExclude drops
            // switch-organization for it. A cross-org switch-project records the
            // other organization, and honoring that would put org-scoped tools
            // outside the pin. Switching project inside the pin stays allowed.
            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '1' }))

            mockSessionScopedStores.get('mcp-session-1')?.set('activeOrgId', switchedOrg)
            mockSessionScopedStores.get('mcp-session-1')?.set('activeProjectId', '2')

            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: '1' }))
            expect(mockTokenStore.get('orgId')).toBe(expectedOrg)
            expect(mockTokenStore.get('projectId')).toBe(expectedProject)
        })

        it('retargets to a project pin that returns after an organization-only pin', async () => {
            // Per-field markers that only compare the fields a request carries leave
            // the old project marker behind when the pin drops that field. The marker
            // then matches when the project pin comes back, so the session keeps the
            // switch and can never retarget to its pin.
            await makeResolver().resolve(makeProps({ projectId: '1' }))
            await makeResolver().resolve(makeProps({ organizationId: 'org-1', projectId: undefined }))
            simulateSwitch('mcp-session-1', '2')

            await makeResolver().resolve(makeProps({ projectId: '1' }))
            expect(mockTokenStore.get('projectId')).toBe('1')
        })

        it('applies the pin on every request without an MCP session id', async () => {
            // No session means no cross-request continuity to protect, so the pin
            // must keep winning each request (single-exec CLI stands alone).
            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: undefined }))
            mockTokenStore.set('projectId', '2')

            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: undefined }))
            expect(mockTokenStore.get('projectId')).toBe('1')
        })

        it('keeps concurrent sessions with different pins on one token isolated', async () => {
            // The token cache is shared by every session on the same credential.
            // Each request must re-assert its own session's context, or one
            // session's pin leaks into the other's queries.
            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: 'session-a' }))
            await makeResolver().resolve(makeProps({ projectId: '2', mcpSessionId: 'session-b' }))
            expect(mockTokenStore.get('projectId')).toBe('2')

            await makeResolver().resolve(makeProps({ projectId: '1', mcpSessionId: 'session-a' }))
            expect(mockTokenStore.get('projectId')).toBe('1')
        })

        it('renews the session-scoped keys TTL on every pinned request', async () => {
            // The keys carry a write-based TTL; without a per-request refresh a
            // switch recorded early in a long session expires first, reads back as
            // a changed pin, and the pin silently wins again.
            await makeResolver().resolve(makeProps({ projectId: '1' }))

            expect(mockRefreshTtlCalls).toContainEqual(
                expect.arrayContaining(['appliedPinOrgId', 'appliedPinProjectId', 'activeOrgId', 'activeProjectId'])
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
})
