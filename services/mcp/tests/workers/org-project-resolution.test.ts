import { env, runInDurableObject } from 'cloudflare:test'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MissingProjectContextError } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'
import type { MCP } from '@/mcp'

// DO-level integration tests for the org/project resolution flow. Exercises the
// real `MCP` class running inside `@cloudflare/vitest-pool-workers` so we get
// the actual DurableObject cache, props pipeline, and `init()` side effects.
//
// The shared workers config (vitest.workers.config.mts) stubs `oauth/introspect`
// to return an active token with empty scopes and 404s every other outbound
// call. That means cold-start `init()` paths that read `users/@me` fall through
// to their wrapped error paths and let init complete.

/**
 * Intercept `ctx.waitUntil` on a Durable Object instance so background promises
 * (e.g. analytics fired at the end of `init()`) can be flushed before the
 * `runInDurableObject` callback returns. Without this, lingering promises access
 * DO storage outside the isolated storage frame and cause timeouts.
 */
function interceptWaitUntil(mcp: MCP): { flush: () => Promise<void> } {
    const pending: Promise<unknown>[] = []
    const ctx = (mcp as any).ctx
    // Replace — do NOT forward to the original. The real `ctx.waitUntil`
    // tells the runtime to keep the DO alive after the handler returns,
    // which means the promise can access storage *after*
    // `runInDurableObject` has already popped the isolated storage frame.
    // Collecting and flushing ourselves keeps all storage access inside
    // the frame.
    ctx.waitUntil = (p: Promise<unknown>) => {
        pending.push(p)
    }
    return {
        async flush() {
            await Promise.allSettled(pending)
            pending.length = 0
        },
    }
}

const propsFor = (
    overrides: Partial<{ projectId: string; organizationId: string; apiToken: string }> = {}
): {
    userHash: string
    apiToken: string
    clientUserAgent: string
    projectId?: string
    organizationId?: string
} => ({
    userHash: 'user-hash-org-project',
    apiToken: overrides.apiToken ?? 'phx_test_token',
    clientUserAgent: 'test-agent',
    ...(overrides.projectId !== undefined ? { projectId: overrides.projectId } : {}),
    ...(overrides.organizationId !== undefined ? { organizationId: overrides.organizationId } : {}),
})

describe('MCP org/project resolution inside the real Workers runtime', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('preserves cached org/project across re-init when no headers are pinned (sticky session)', async () => {
        const setDefaultSpy = vi.spyOn(StateManager.prototype, 'setDefaultOrganizationAndProject')
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-sticky-cached'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            const bg = interceptWaitUntil(mcp)
            ;(mcp as any).props = propsFor()
            await mcp.cache.set('orgId', 'previously-picked-org')
            await mcp.cache.set('projectId', 'previously-picked-project')

            await mcp.init()

            // Cache already pinned a project from a prior session — init must not
            // overwrite it with whatever `users/@me` currently returns.
            expect(setDefaultSpy).not.toHaveBeenCalled()
            expect(await mcp.cache.get('orgId')).toBe('previously-picked-org')
            expect(await mcp.cache.get('projectId')).toBe('previously-picked-project')

            await bg.flush()
        })
    })

    it('resolves defaults via setDefault... on a cold session with no headers and no cache', async () => {
        // Stub the resolver so we don't depend on the (404-mocked) PostHog API
        // for the inputs. We're verifying that init() *invokes* it on a cold
        // session — the resolver itself is unit-tested separately.
        const setDefaultSpy = vi
            .spyOn(StateManager.prototype, 'setDefaultOrganizationAndProject')
            .mockImplementation(async function (this: StateManager) {
                await (this as any)._cache.set('orgId', 'resolved-org')
                await (this as any)._cache.set('projectId', 'resolved-project')
                return { organizationId: 'resolved-org', projectId: 999 }
            })

        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-cold-no-cache'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            const bg = interceptWaitUntil(mcp)
            ;(mcp as any).props = propsFor()
            // No prior cache — fresh DO for this userHash.

            await mcp.init()

            expect(setDefaultSpy).toHaveBeenCalledOnce()
            expect(await mcp.cache.get('orgId')).toBe('resolved-org')
            expect(await mcp.cache.get('projectId')).toBe('resolved-project')

            await bg.flush()
        })
    })

    it('header-pinned projectId overrides a previously cached value (header wins)', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-header-overrides-cache'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            const bg = interceptWaitUntil(mcp)
            ;(mcp as any).props = propsFor()
            // Simulate a prior session that cached an org + project.
            await mcp.cache.set('orgId', 'cached-org')
            await mcp.cache.set('projectId', 'old-cached-project')
            ;(mcp as any).props = propsFor({ projectId: 'new-header-project' })

            await mcp.init()

            // Header wins on projectId; orgId is left as-is.
            expect(await mcp.cache.get('projectId')).toBe('new-header-project')
            expect(await mcp.cache.get('orgId')).toBe('cached-org')

            await bg.flush()
        })
    })

    it('does not throw for multi-team scoped API keys when the active team is not in the scope', async () => {
        // Simulate the production scenario from cf-ray 9f0c989fbe7d0469: a personal
        // API key scoped to multiple teams, none of which is the user's currently
        // active team. The pre-fix resolver threw "API key has access to multiple
        // projects..." here; the rewrite must pick scoped_teams[0] deterministically.
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-multi-team-scope'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            ;(mcp as any).props = propsFor()

            // Reach into the StateManager that init() would build via getContext().
            const context = await (mcp as any).getContext()
            const sm: StateManager = context.stateManager

            vi.spyOn(sm, 'getApiKey').mockResolvedValue({
                scopes: [],
                scoped_teams: [111, 222, 333],
                scoped_organizations: [],
            })
            vi.spyOn(sm, 'getUser').mockResolvedValue({
                distinct_id: 'distinct-multi-team',
                email: 'multi@example.com',
                organizations: [],
                team: { id: 999, name: 'Active', timezone: 'UTC', organization: 'org-active' },
                organization: { id: 'org-active', name: 'Active' },
            } as any)

            const resolved = await sm.setDefaultOrganizationAndProject()

            expect(resolved.projectId).toBe(111) // first scoped team
            expect(await mcp.cache.get('projectId')).toBe('111')
        })
    })

    it('prefers the active team when it is in the multi-team scope', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-multi-team-active-in-scope'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            ;(mcp as any).props = propsFor()
            const sm: StateManager = (await (mcp as any).getContext()).stateManager

            vi.spyOn(sm, 'getApiKey').mockResolvedValue({
                scopes: [],
                scoped_teams: [111, 222, 333],
                scoped_organizations: [],
            })
            vi.spyOn(sm, 'getUser').mockResolvedValue({
                distinct_id: 'distinct-active-in-scope',
                email: 'active@example.com',
                organizations: [],
                team: { id: 222, name: 'Active', timezone: 'UTC', organization: 'org-active' },
                organization: { id: 'org-active', name: 'Active' },
            } as any)

            const resolved = await sm.setDefaultOrganizationAndProject()

            expect(resolved.projectId).toBe(222) // the active team, not scoped_teams[0]
            expect(await mcp.cache.get('projectId')).toBe('222')
        })
    })

    it('getProjectId throws MissingProjectContextError with the scoped org when no project is resolvable', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-missing-project'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            ;(mcp as any).props = propsFor()
            const sm: StateManager = (await (mcp as any).getContext()).stateManager

            vi.spyOn(sm, 'getApiKey').mockResolvedValue({
                scopes: [],
                scoped_teams: [],
                scoped_organizations: ['org-out-of-reach'],
            })
            vi.spyOn(sm, 'getUser').mockResolvedValue({
                distinct_id: 'distinct-no-project',
                email: 'noproj@example.com',
                organizations: [],
                team: { id: 999, name: 'Active', timezone: 'UTC', organization: 'org-different' },
                organization: { id: 'org-different', name: 'Different' },
            } as any)
            // Make the projects-list call fail so the resolver returns just the org.
            ;(sm as any)._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({ success: false, error: new Error('boom') }),
                    }),
                }),
            }

            await expect(sm.getProjectId()).rejects.toMatchObject({
                name: 'MissingProjectContextError',
                organizationId: 'org-out-of-reach',
            })

            try {
                await sm.getProjectId()
            } catch (err) {
                expect(err).toBeInstanceOf(MissingProjectContextError)
                expect((err as Error).message).toContain('switch-project')
                expect((err as Error).message).toContain('org-out-of-reach')
            }
        })
    })
})
