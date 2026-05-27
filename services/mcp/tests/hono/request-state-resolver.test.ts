import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { RequestContext } from '@/hono/request-context'
import { RequestStateResolver } from '@/hono/request-state-resolver'
import type { ToolCatalog } from '@/hono/tool-catalog'
import { StateManager } from '@/lib/StateManager'
import type { RequestProperties } from '@/lib/request-properties'
import { hash } from '@/lib/utils'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

// `evaluateFeatureFlags` reaches out to the PostHog node-client; resolver
// always hits it once for the `SYSTEM_FLAGS` array. Stub with a real impl
// (not `.mockResolvedValue`) so it survives `vi.restoreAllMocks()` between
// tests — `restoreAllMocks` resets explicit return values to the original
// implementation, which would be empty for a bare `vi.fn()`.
vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({})),
}))

// `getPostHogClient` is touched indirectly via `_reportException` paths in
// StateManager. We mock all the StateManager surface area we care about, but
// keep this guard in case a future change exercises the real client.
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ capture: vi.fn(), captureException: vi.fn() }),
}))

function fakeRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => {
            let n = 0
            for (const k of keys) {
                if (store.delete(k)) {
                    n++
                }
            }
            return n
        },
        scan: async () => ['0', [...store.keys()]],
        ...makeRedisRateLimitStubs(),
    }
}

const env = {} as any

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        userHash: 'user-hash-resolver',
        apiToken: 'phx_test_token',
        clientUserAgent: 'test-agent',
        requestStartTime: Date.now(),
        ...overrides,
    }
}

/**
 * Build a `RequestStateResolver` whose collaborators have been short-circuited
 * to keep the test deterministic and offline. The bits we care about — token
 * cache writes, session cache writes, and the `setDefault…` branch — are still
 * exercised against real `RedisCache` instances backed by `redis`.
 */
function buildResolver(redis: RedisLike): {
    resolver: RequestStateResolver
    setDefaultSpy: ReturnType<typeof vi.spyOn>
} {
    const catalogStub = {
        getFilteredTools: vi.fn().mockReturnValue([]),
    } as unknown as ToolCatalog

    // StateManager is instantiated per-request by `RequestContext.getContext`.
    // Prototype spies catch every instance the resolver creates.
    const setDefaultSpy = vi.spyOn(StateManager.prototype, 'setDefaultOrganizationAndProject').mockResolvedValue({
        organizationId: 'resolved-org',
        projectId: 999,
    })
    vi.spyOn(StateManager.prototype, 'getApiKey').mockResolvedValue({
        scopes: [],
        scoped_teams: [],
        scoped_organizations: [],
    })
    vi.spyOn(StateManager.prototype, 'getAiConsentGiven').mockResolvedValue(undefined)
    vi.spyOn(StateManager.prototype, 'getAnalyticsContext').mockResolvedValue({})

    // The resolver fans out into `reqCtx.getDistinctId()` which would otherwise
    // hit `users/@me` over HTTP. Short-circuit it.
    vi.spyOn(RequestContext.prototype, 'getDistinctId').mockResolvedValue('distinct-test')

    const resolver = new RequestStateResolver(catalogStub, redis, env)
    return { resolver, setDefaultSpy }
}

describe('RequestStateResolver', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    describe('projectId resolution', () => {
        let redis: RedisLike
        beforeEach(() => {
            redis = fakeRedis()
        })

        it('writes header-pinned projectId into the token cache and skips setDefault', async () => {
            const { resolver, setDefaultSpy } = buildResolver(redis)

            await resolver.resolve(makeProps({ projectId: 'header-project' }))

            // The header-pinned value lands in the token cache verbatim. The
            // standard cache key format includes the prefix and the userHash.
            const cached = await redis.get('mcp:token:user-hash-resolver:projectId')
            expect(cached).not.toBeNull()
            expect(JSON.parse(cached!)).toBe('header-project')

            // Resolver short-circuits the default-resolution branch because a
            // projectId is already in scope for the request.
            expect(setDefaultSpy).not.toHaveBeenCalled()
        })

        it('header-pinned projectId overrides a previously cached value (header wins)', async () => {
            await redis.set('mcp:token:user-hash-resolver:projectId', JSON.stringify('old-cached-project'))
            const { resolver, setDefaultSpy } = buildResolver(redis)

            await resolver.resolve(makeProps({ projectId: 'new-header-project' }))

            const cached = await redis.get('mcp:token:user-hash-resolver:projectId')
            expect(JSON.parse(cached!)).toBe('new-header-project')
            expect(setDefaultSpy).not.toHaveBeenCalled()
        })

        it('preserves the cached projectId when no header is pinned (sticky session)', async () => {
            await redis.set('mcp:token:user-hash-resolver:projectId', JSON.stringify('previously-picked-project'))
            const { resolver, setDefaultSpy } = buildResolver(redis)

            await resolver.resolve(makeProps())

            const cached = await redis.get('mcp:token:user-hash-resolver:projectId')
            expect(JSON.parse(cached!)).toBe('previously-picked-project')
            // Critically: the resolver must NOT invoke setDefault when a cached
            // project is already pinned — that would silently re-resolve the
            // session against the user's current active team.
            expect(setDefaultSpy).not.toHaveBeenCalled()
        })

        it('invokes setDefault when neither header nor cache supplies a projectId', async () => {
            const { resolver, setDefaultSpy } = buildResolver(redis)

            await resolver.resolve(makeProps())

            expect(setDefaultSpy).toHaveBeenCalledOnce()
        })

        it('also writes header-pinned organizationId into the token cache', async () => {
            const { resolver } = buildResolver(redis)

            await resolver.resolve(makeProps({ organizationId: 'header-org', projectId: 'header-project' }))

            const orgCached = await redis.get('mcp:token:user-hash-resolver:orgId')
            expect(orgCached).not.toBeNull()
            expect(JSON.parse(orgCached!)).toBe('header-org')
        })
    })

    describe('client-info resolution via session cache', () => {
        const sessionId = 'sess-client-info'
        const sessionScope = hash(sessionId)
        const sessionKey = (key: string): string => `mcp:session:${sessionScope}:${key}`

        let redis: RedisLike
        beforeEach(() => {
            redis = fakeRedis()
        })

        it('seeds session cache on the initialize request', async () => {
            const { resolver } = buildResolver(redis)

            await resolver.resolve(
                makeProps({
                    mcpSessionId: sessionId,
                    mcpClientName: 'claude-code',
                    mcpClientVersion: '1.0.42',
                    mcpProtocolVersion: '2024-11-05',
                })
            )

            expect(JSON.parse((await redis.get(sessionKey('mcpClientName')))!)).toBe('claude-code')
            expect(JSON.parse((await redis.get(sessionKey('mcpClientVersion')))!)).toBe('1.0.42')
            expect(JSON.parse((await redis.get(sessionKey('mcpProtocolVersion')))!)).toBe('2024-11-05')
        })

        it('hydrates a follow-up tool-call request from the session cache when the props lack client info', async () => {
            // Simulate the cache state left behind by an earlier initialize on
            // the same session.
            await redis.set(sessionKey('mcpClientName'), JSON.stringify('cursor'))
            await redis.set(sessionKey('mcpClientVersion'), JSON.stringify('0.42.1'))
            await redis.set(sessionKey('mcpProtocolVersion'), JSON.stringify('2024-11-05'))

            const { resolver } = buildResolver(redis)
            const props = makeProps({ mcpSessionId: sessionId })

            const state = await resolver.resolve(props)

            // Resolver mutates the props in-place so downstream call sites
            // (analytics, ApiClient construction) see the hydrated values.
            expect(props.mcpClientName).toBe('cursor')
            expect(props.mcpClientVersion).toBe('0.42.1')
            expect(props.mcpProtocolVersion).toBe('2024-11-05')

            // The resolved clientProfile reflects the cached client info too.
            expect(state.clientProfile).toMatchObject({ clientName: 'cursor', clientVersion: '0.42.1' })
        })

        it('does not write to session cache when mcpSessionId is absent', async () => {
            const { resolver } = buildResolver(redis)

            await resolver.resolve(
                makeProps({
                    mcpClientName: 'claude-code',
                    mcpClientVersion: '1.0.42',
                    mcpProtocolVersion: '2024-11-05',
                })
            )

            // Session-scoped keys would require a sessionId scope; with none
            // provided, nothing should land under any session prefix.
            expect(await redis.get(sessionKey('mcpClientName'))).toBeNull()
        })

        it('header-supplied client info wins over cached session values', async () => {
            await redis.set(sessionKey('mcpClientName'), JSON.stringify('stale-cached'))
            await redis.set(sessionKey('mcpClientVersion'), JSON.stringify('0.0.0'))
            await redis.set(sessionKey('mcpProtocolVersion'), JSON.stringify('old-proto'))

            const { resolver } = buildResolver(redis)
            const props = makeProps({
                mcpSessionId: sessionId,
                mcpClientName: 'fresh-from-init',
                mcpClientVersion: '2.0.0',
                mcpProtocolVersion: '2025-03-26',
            })

            await resolver.resolve(props)

            // The fresh values overwrite the cached ones.
            expect(props.mcpClientName).toBe('fresh-from-init')
            expect(JSON.parse((await redis.get(sessionKey('mcpClientName')))!)).toBe('fresh-from-init')
        })
    })

    describe('token rotation across the same mcp-session-id', () => {
        // OAuth refresh emits a new bearer token but well-behaved clients keep
        // the same `Mcp-Session-Id` for transport continuity. The cache must
        // partition on `userHash = hash(token)` so token-A's resolved
        // projectId / distinctId never leak into token-B's request — while the
        // *session* cache stays shared so the client identity (name/version/
        // protocol) outlives the rotation.

        const sessionId = 'sess-rotated'
        const tokenA = 'phx_token_a'
        const tokenB = 'phx_token_b'
        const sessionScope = hash(sessionId)
        const tokenAScope = hash(tokenA)
        const tokenBScope = hash(tokenB)

        let redis: RedisLike
        beforeEach(() => {
            redis = fakeRedis()
        })

        it('serves fresh token-scoped cache when the same session-id is reused with a new token', async () => {
            const { resolver, setDefaultSpy } = buildResolver(redis)

            // Phase 1 — token-A pins project-A and seeds the session-scoped
            // client info. Header is the projectId source, so `setDefault…`
            // does not fire.
            await resolver.resolve(
                makeProps({
                    userHash: tokenAScope,
                    apiToken: tokenA,
                    mcpSessionId: sessionId,
                    mcpClientName: 'claude-code',
                    mcpClientVersion: '1.0.0',
                    mcpProtocolVersion: '2024-11-05',
                    projectId: 'project-A',
                })
            )
            expect(setDefaultSpy).not.toHaveBeenCalled()
            expect(JSON.parse((await redis.get(`mcp:token:${tokenAScope}:projectId`))!)).toBe('project-A')

            // Phase 2 — token-B reuses the same session-id; no projectId
            // header. If token-A's tokenCache leaked across, the resolver
            // would read 'project-A' and short-circuit `setDefault…`.
            const propsB = makeProps({
                userHash: tokenBScope,
                apiToken: tokenB,
                mcpSessionId: sessionId,
            })
            await resolver.resolve(propsB)

            // Token-scoped lookup missed → `setDefault…` was invoked exactly
            // once for token-B's request, proving the cache is partitioned by
            // userHash and not leaking across the rotation.
            expect(setDefaultSpy).toHaveBeenCalledOnce()

            // Token-A's scope is untouched and isolated; token-B's scope holds
            // nothing yet because the `setDefault…` mock is stubbed to not
            // write through (the *write* path is exercised elsewhere — the
            // contract that matters here is that the *read* missed).
            expect(JSON.parse((await redis.get(`mcp:token:${tokenAScope}:projectId`))!)).toBe('project-A')
            expect(await redis.get(`mcp:token:${tokenBScope}:projectId`)).toBeNull()

            // Session-scoped data is intentionally shared across the rotation
            // — client identity survives an OAuth refresh.
            expect(propsB.mcpClientName).toBe('claude-code')
            expect(propsB.mcpClientVersion).toBe('1.0.0')
            expect(propsB.mcpProtocolVersion).toBe('2024-11-05')
            expect(JSON.parse((await redis.get(`mcp:session:${sessionScope}:mcpClientName`))!)).toBe('claude-code')
        })

        it('keyspaces tokenCache writes per-token even when sessions are interleaved', async () => {
            // Two concurrent sessions on the same client process — distinct
            // tokens, distinct session-ids — must not share a tokenCache row.
            const { resolver } = buildResolver(redis)

            await resolver.resolve(
                makeProps({
                    userHash: tokenAScope,
                    apiToken: tokenA,
                    mcpSessionId: 'sess-a',
                    projectId: 'project-A',
                })
            )
            await resolver.resolve(
                makeProps({
                    userHash: tokenBScope,
                    apiToken: tokenB,
                    mcpSessionId: 'sess-b',
                    projectId: 'project-B',
                })
            )

            expect(JSON.parse((await redis.get(`mcp:token:${tokenAScope}:projectId`))!)).toBe('project-A')
            expect(JSON.parse((await redis.get(`mcp:token:${tokenBScope}:projectId`))!)).toBe('project-B')
        })
    })
})
