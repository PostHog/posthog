import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { StateLookupCache } from '@/lib/cache/StateLookupCache'
import { PostHogApiError } from '@/lib/errors'
import { getPostHogClient } from '@/lib/posthog'
import { StateManager } from '@/lib/StateManager'
import type { ApiRedactedPersonalApiKey, ApiUser } from '@/schema/api'
import type { PinnedActiveContext, SessionScopedState, State } from '@/tools/types'

describe('StateManager', () => {
    let stateManager: StateManager
    let cache: MemoryCache<State>
    const mockUser: ApiUser = {
        distinct_id: 'distinct-123',
        email: 'test@example.com',
        organizations: [
            { id: 'org-1', name: 'Org 1' },
            { id: 'org-2', name: 'Org 2' },
        ],
        team: { id: 456, name: 'My Project', timezone: 'UTC', organization: 'org-1' },
        organization: { id: 'org-1', name: 'Org 1' },
    }

    const mockApiKey: ApiRedactedPersonalApiKey = {
        scopes: ['user:read', 'insight:write'],
        scoped_organizations: [],
        scoped_teams: [],
    }

    beforeEach(async () => {
        cache = new MemoryCache('test-user')
        await cache.clear()
        stateManager = new StateManager(cache, {} as ApiClient)
    })

    it.each([
        {
            lookup: 'organization',
            context: { pin: { projectId: '456' }, projectId: '456' },
            resolve: (manager: StateManager) => manager.getOrgID(),
            expected: 'org-1',
        },
        {
            lookup: 'project',
            context: { pin: { organizationId: 'org-1' }, orgId: 'org-1' },
            resolve: (manager: StateManager) => manager.getProjectId(),
            expected: '456',
        },
        {
            lookup: 'default',
            context: { pin: {} },
            resolve: (manager: StateManager) => manager.setDefaultOrganizationAndProject(),
            expected: { organizationId: 'org-1', projectId: 456 },
        },
        {
            lookup: 'initialization',
            context: { pin: {} },
            resolve: (manager: StateManager) => manager.setDefaultOrganizationAndProject(),
            expected: { organizationId: 'org-2', projectId: 789 },
        },
    ])(
        'preserves a newer selection when an older $lookup lookup finishes',
        async ({ lookup, context, resolve, expected }) => {
            const sessionCache = new MemoryCache<SessionScopedState>(`stale-${lookup}`)
            await sessionCache.clear()
            await cache.setMany({
                apiKey: lookup === 'project' ? { ...mockApiKey, scoped_teams: [456] } : mockApiKey,
                apiKeyFetchedAt: Date.now(),
            })
            let finishLookup!: () => void
            let lookupRequested!: () => void
            const requested = new Promise<void>((resolve) => {
                lookupRequested = resolve
            })
            const gate = new Promise<void>((resolve) => {
                finishLookup = resolve
            })
            const api = {
                config: { apiToken: 'phx_test' },
                users: () => ({
                    me: async () => {
                        if (lookup === 'default' || lookup === 'initialization') {
                            lookupRequested()
                            await gate
                        }
                        return { success: true, data: mockUser }
                    },
                }),
                projects: () => ({
                    get: async () => {
                        lookupRequested()
                        await gate
                        return { success: true, data: { id: 456, organization: 'org-1' } }
                    },
                }),
            } as unknown as ApiClient
            const snapshot = (): PinnedActiveContext => ({
                ...context,
                sessionScoped: true,
            })
            const older = new StateManager(cache, api, snapshot(), sessionCache)
            const currentApi = {
                ...api,
                users: () => ({
                    me: async () => ({
                        success: true,
                        data: {
                            ...mockUser,
                            organization: { id: 'org-2', name: 'Other organization' },
                            team: { id: 789, name: 'Other project', organization: 'org-2' },
                        },
                    }),
                }),
            } as unknown as ApiClient
            const newer = new StateManager(cache, currentApi, snapshot(), sessionCache)
            const pending = resolve(older)
            await requested
            try {
                if (lookup === 'initialization') {
                    await newer.setDefaultOrganizationAndProject()
                } else {
                    await newer.setActiveContext({ orgId: 'org-2', projectId: '789' })
                }
            } finally {
                finishLookup()
            }

            const resolved = await pending
            const defaults = await sessionCache.get('defaultContext')
            expect({
                resolved,
                orgId: (await sessionCache.get('activeOrgId')) ?? defaults?.organizationId,
                projectId: (await sessionCache.get('activeProjectId')) ?? defaults?.projectId?.toString(),
            }).toEqual({
                resolved: expected,
                orgId: 'org-2',
                projectId: '789',
            })
        }
    )

    it.each([true, false, undefined])('reports lookup errors with cached suppression=%s', async (suppressed) => {
        const capture = vi.spyOn(getPostHogClient(), 'captureException').mockImplementation(() => {})
        const error = new Error('Synthetic project lookup failure')
        const lookup = vi
            .spyOn(stateManager, 'getApiKey')
            .mockRejectedValue(new Error('Synthetic introspection failure'))
        if (suppressed === undefined) {
            vi.spyOn(cache, 'get').mockRejectedValue(new Error('Synthetic cache failure'))
        } else {
            await cache.set('apiKey', { ...mockApiKey, suppress_analytics: suppressed })
        }

        await (stateManager as any)._reportException(error, 'default_org_project_projects_list_failed')

        expect(capture).toHaveBeenCalledWith(
            error,
            undefined,
            expect.objectContaining({ suppress_analytics: suppressed === true })
        )
        expect(lookup).not.toHaveBeenCalled()
        capture.mockRestore()
    })

    describe('getUser', () => {
        it.each(['user', 'credential'] as const)(
            'shares a failed %s lookup and permits a later retry',
            async (kind) => {
                const load = vi
                    .fn()
                    .mockRejectedValueOnce(new Error('Synthetic lookup failure'))
                    .mockResolvedValue({ success: true, data: kind === 'user' ? mockUser : mockApiKey })
                const api = {
                    config: { apiToken: 'phx_test' },
                    users: () => ({ me: load }),
                    apiKeys: () => ({ current: load }),
                } as unknown as ApiClient
                const lookups = new StateLookupCache()
                const first = new StateManager(cache, api, undefined, undefined, lookups)
                const second = new StateManager(cache, api, undefined, undefined, lookups)
                const get = (manager: StateManager): Promise<unknown> =>
                    kind === 'user' ? manager.getUser() : manager.getApiKey()
                const failed = await Promise.allSettled([get(first), get(second)])
                expect(failed.map(({ status }) => status)).toEqual(['rejected', 'rejected'])
                expect(load).toHaveBeenCalledTimes(1)
                expect(await get(second)).toMatchObject(kind === 'user' ? mockUser : mockApiKey)
                expect(load).toHaveBeenCalledTimes(2)
            }
        )

        it('keeps shared lookup results bound to their credential cache scope', async () => {
            const lookups = new StateLookupCache()
            const managers = ['first-credential', 'second-credential'].map((scope) => {
                const scopedCache = new MemoryCache<State>(scope)
                const api = {
                    users: () => ({ me: async () => ({ success: true, data: { ...mockUser, distinct_id: scope } }) }),
                } as unknown as ApiClient
                return new StateManager(scopedCache, api, undefined, undefined, lookups)
            })
            expect(
                (await Promise.all(managers.map((manager) => manager.getUser()))).map((user) => user.distinct_id)
            ).toEqual(['first-credential', 'second-credential'])
        })

        it('should fetch and cache user on first call', async () => {
            const fetchUserSpy = vi.spyOn(stateManager as any, '_fetchUser').mockResolvedValue(mockUser)

            const result = await stateManager.getUser()

            expect(result).toEqual(mockUser)
            expect(fetchUserSpy).toHaveBeenCalledOnce()
        })

        it('should return cached user on subsequent calls', async () => {
            const fetchUserSpy = vi.spyOn(stateManager as any, '_fetchUser').mockResolvedValue(mockUser)

            await stateManager.getUser()
            const result = await stateManager.getUser()

            expect(result).toEqual(mockUser)
            expect(fetchUserSpy).toHaveBeenCalledOnce()
        })

        it('should throw error when user fetch fails', async () => {
            const error = new Error('API error')
            vi.spyOn(stateManager as any, '_fetchUser').mockRejectedValue(error)

            await expect(stateManager.getUser()).rejects.toThrow('API error')
        })
    })

    describe('getDistinctId', () => {
        it('should get distinct ID from cache if available', async () => {
            await cache.set('distinctId', 'cached-distinct-id')

            const result = await stateManager.getDistinctId()

            expect(result).toBe('cached-distinct-id')
        })

        it('should fetch user and cache distinct ID if not in cache', async () => {
            const getUserSpy = vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.getDistinctId()

            expect(result).toBe('distinct-123')
            expect(await cache.get('distinctId')).toBe('distinct-123')
            expect(getUserSpy).toHaveBeenCalledOnce()
        })
    })

    describe('getApiKey', () => {
        const cacheOnlyApi = { config: { apiToken: 'phx_test' } } as unknown as ApiClient
        const cacheOnlyOauthApi = { config: { apiToken: 'pha_test' } } as unknown as ApiClient

        function oauthApi(clientName: string | null, impersonated?: boolean, scope = 'insight:read'): ApiClient {
            return {
                config: { apiToken: 'pha_test' },
                apiKeys: () => ({
                    current: async () => ({ success: false, error: { message: 'not a personal key' } }),
                }),
                oauth: () => ({
                    introspect: async () => ({
                        success: true,
                        data: {
                            active: true,
                            scope,
                            client_name: clientName,
                            is_impersonated: impersonated,
                        },
                    }),
                }),
            } as unknown as ApiClient
        }

        it.each([
            { impersonated: true, scope: 'insight:read', suppressed: false },
            { impersonated: false, scope: 'insight:read', suppressed: false },
            { impersonated: undefined, scope: 'insight:read', suppressed: false },
            { impersonated: false, scope: 'insight:read scout_experiment_internal:read', suppressed: true },
        ])(
            'caches impersonation=$impersonated and capture suppression=$suppressed from token scope',
            async ({ impersonated, scope, suppressed }) => {
                stateManager = new StateManager(cache, oauthApi(null, impersonated, scope))

                const result = await stateManager.getApiKey()

                expect(result.is_impersonated).toBe(impersonated === true)
                expect(result.suppress_analytics).toBe(suppressed)
                expect(await new StateManager(cache, cacheOnlyOauthApi).getApiKey()).toEqual(result)

                const otherTokenCache = new MemoryCache<State>('other-token')
                await otherTokenCache.clear()
                const otherToken = new StateManager(otherTokenCache, oauthApi(null, false))
                expect((await otherToken.getApiKey()).is_impersonated).toBe(false)
                expect((await otherToken.getApiKey()).suppress_analytics).toBe(false)
                expect((await stateManager.getApiKey()).is_impersonated).toBe(impersonated === true)
                expect((await stateManager.getApiKey()).suppress_analytics).toBe(suppressed)
            }
        )

        it.each([{ scopes: [] }, { scopes: ['scout_experiment_internal:read'] }])(
            'does not suppress personal-key telemetry for scopes $scopes',
            async ({ scopes }) => {
                const apiKey = { ...mockApiKey, scopes, suppress_analytics: true }
                const api = {
                    config: { apiToken: 'phx_test' },
                    apiKeys: () => ({ current: async () => ({ success: true, data: apiKey }) }),
                } as unknown as ApiClient

                const result = await new StateManager(cache, api).getApiKey()

                expect(result).toEqual({ ...apiKey, is_impersonated: false, suppress_analytics: false })
                expect(await new StateManager(cache, cacheOnlyApi).getApiKey()).toEqual(result)
            }
        )

        it.each([
            { apiToken: 'phx_test', expectedScopes: ['user:read', 'cdp:read'] },
            { apiToken: 'unrecognized-token', expectedScopes: ['user:read', 'cdp:read'] },
            { apiToken: 'pha_test', expectedScopes: mockApiKey.scopes },
        ])(
            're-reads expired scopes only for a token that keeps its value ($apiToken)',
            async ({ apiToken, expectedScopes }) => {
                vi.useFakeTimers()
                try {
                    const current = vi
                        .fn()
                        .mockResolvedValueOnce({ success: true, data: mockApiKey })
                        .mockResolvedValue({
                            success: true,
                            data: { ...mockApiKey, scopes: ['user:read', 'cdp:read'] },
                        })
                    const api = { config: { apiToken }, apiKeys: () => ({ current }) } as unknown as ApiClient
                    const manager = new StateManager(cache, api)

                    expect((await manager.getApiKey()).scopes).toEqual(mockApiKey.scopes)

                    vi.advanceTimersByTime(60 * 1000)
                    expect((await manager.getApiKey()).scopes).toEqual(mockApiKey.scopes)

                    vi.advanceTimersByTime(2 * 60 * 1000)
                    expect((await manager.getApiKey()).scopes).toEqual(expectedScopes)
                } finally {
                    vi.useRealTimers()
                }
            }
        )

        it('keeps the cached scopes when a refresh fails', async () => {
            vi.useFakeTimers()
            try {
                const current = vi
                    .fn()
                    .mockResolvedValueOnce({ success: true, data: mockApiKey })
                    .mockRejectedValue(new Error('API unreachable'))
                const api = { config: { apiToken: 'phx_test' }, apiKeys: () => ({ current }) } as unknown as ApiClient

                await new StateManager(cache, api).getApiKey()
                vi.advanceTimersByTime(3 * 60 * 1000)

                expect((await new StateManager(cache, api).getApiKey()).scopes).toEqual(mockApiKey.scopes)
            } finally {
                vi.useRealTimers()
            }
        })

        it.each([
            { label: 'a 401', error: new Error('INVALID_API_KEY: token revoked'), rejected: true },
            {
                label: 'a 403 for an unknown token',
                error: new PostHogApiError({
                    status: 403,
                    statusText: 'Forbidden',
                    body: '',
                    url: 'https://us.posthog.com/oauth/introspect',
                    method: 'POST',
                }),
                rejected: true,
            },
            {
                label: 'a 503',
                error: new PostHogApiError({
                    status: 503,
                    statusText: 'Service Unavailable',
                    body: '',
                    url: 'https://us.posthog.com/oauth/introspect',
                    method: 'POST',
                }),
                rejected: false,
            },
            { label: 'an outage', error: new Error('Network error: fetch failed'), rejected: false },
        ])(
            'reports an introspection failure from $label as a rejection only when the token is refused',
            async ({ error: introspectError, rejected }) => {
                const api = {
                    config: { apiToken: 'pha_test' },
                    apiKeys: () => ({
                        current: async () => ({ success: false, error: { message: 'not a personal key' } }),
                    }),
                    oauth: () => ({ introspect: async () => ({ success: false, error: introspectError }) }),
                } as unknown as ApiClient

                const error = await new StateManager(cache, api).getApiKey().catch((e: Error) => e)

                expect(error).toBeInstanceOf(Error)
                expect((error as Error).message.includes('INVALID_API_KEY')).toBe(rejected)
            }
        )

        it.each([
            { label: 'an OAuth app name', clientName: 'Claude', expected: 'Claude' },
            { label: 'no OAuth app name', clientName: null, expected: undefined },
        ])('stamps $label onto the live client so the same request forwards it', async ({ clientName, expected }) => {
            const api = oauthApi(clientName)
            const secondApi = oauthApi(clientName)
            const lookups = new StateLookupCache()
            stateManager = new StateManager(cache, api, undefined, undefined, lookups)
            const second = new StateManager(cache, secondApi, undefined, undefined, lookups)

            await Promise.all([stateManager.getApiKey(), second.getApiKey()])

            expect(api.config.oauthClientName).toBe(expected)
            expect(secondApi.config.oauthClientName).toBe(expected)
            expect(await cache.get('clientName')).toBe(expected)
        })
    })

    describe('setDefaultOrganizationAndProject', () => {
        it('should handle team-scoped API key with single team', async () => {
            const teamScopedApiKey = {
                ...mockApiKey,
                scoped_teams: [456],
            }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(teamScopedApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.projectId).toBe(456)
            expect(result.organizationId).toBeUndefined()
        })

        it('should prefer the active team when it is in a multi-team scoped list', async () => {
            const multiTeamApiKey = {
                ...mockApiKey,
                scoped_teams: [123, 456, 789],
            }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(multiTeamApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.projectId).toBe(456)
            expect(result.organizationId).toBeUndefined()
            expect(await cache.get('projectId')).toBe('456')
        })

        it('should fall back to the first scoped team when the active team is not in the list', async () => {
            const multiTeamApiKey = {
                ...mockApiKey,
                scoped_teams: [123, 789],
            }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(multiTeamApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.projectId).toBe(123)
            expect(result.organizationId).toBeUndefined()
            expect(await cache.get('projectId')).toBe('123')
        })

        it("should use user's active org and team when no scoped restrictions", async () => {
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(mockApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-1')
            expect(result.projectId).toBe(456)
            expect(await cache.get('orgId')).toBe('org-1')
            expect(await cache.get('projectId')).toBe('456')
        })

        it("should use user's active org and team when org is in scoped list", async () => {
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-2', 'org-1'],
            }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-1')
            expect(result.projectId).toBe(456)
        })

        it("should use first scoped org when user's active org not in scoped list", async () => {
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-3'],
            }

            const mockApi = stateManager as any
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            // Mock the API client organization projects list call
            mockApi._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({
                            success: true,
                            data: [{ id: 789 }],
                        }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBe(789)
        })

        it('returns the org alone when no projects are available for the scoped org', async () => {
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-3'],
            }

            const mockApi = stateManager as any
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)

            mockApi._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({
                            success: true,
                            data: [],
                        }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBeUndefined()
            expect(await cache.get('orgId')).toBe('org-3')
            expect(await cache.get('projectId')).toBeUndefined()
        })

        it('falls back to the first scoped team when the user has no active team', async () => {
            // Regression: `/api/users/@me/` returns `team: null` when the user
            // has no `current_team` (newly provisioned account, left last
            // org). Reading `.id` on the null team would 500 the whole request
            // before any tool dispatch.
            const teamScopedApiKey = {
                ...mockApiKey,
                scoped_teams: [123, 456],
            }
            const userWithoutCurrent: ApiUser = { ...mockUser, team: null, organization: null }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(teamScopedApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(userWithoutCurrent)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.projectId).toBe(123)
            expect(result.organizationId).toBeUndefined()
        })

        it('falls back to the first scoped org when the user has no active org', async () => {
            // Same regression for the org-scoped branch: reading
            // `activeOrganization.id` on null would 500 the request.
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-3'],
            }
            const userWithoutCurrent: ApiUser = { ...mockUser, team: null, organization: null }

            const mockApi = stateManager as any
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(userWithoutCurrent)

            mockApi._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({ success: true, data: [{ id: 789 }] }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBe(789)
        })

        it('returns empty context when the user has no active org and the key is unscoped', async () => {
            // With nothing to anchor on (no scoped teams, no scoped orgs, no
            // current_organization) the resolver should surface a recoverable
            // missing-context state rather than crash or fabricate an org id.
            const userWithoutCurrent: ApiUser = { ...mockUser, team: null, organization: null }

            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(mockApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(userWithoutCurrent)

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBeUndefined()
            expect(result.projectId).toBeUndefined()
        })

        it('returns the org alone when the projects fetch fails', async () => {
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-3'],
            }

            const mockApi = stateManager as any
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)
            const reportSpy = vi.spyOn(stateManager as any, '_reportException').mockImplementation(() => {})

            mockApi._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({
                            success: false,
                            error: new Error('Projects fetch failed'),
                        }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBeUndefined()
            // Unexpected failures still reach error tracking.
            expect(reportSpy).toHaveBeenCalledOnce()
        })

        it.each(['503', 'timeout', 'empty'])('recovers a session default after a project-list %s', async (failure) => {
            const sessionCache = new MemoryCache<SessionScopedState>(`default-recovery-${failure}`)
            await sessionCache.clear()
            await cache.setMany({
                apiKey: { ...mockApiKey, scoped_organizations: ['org-3', 'org-2'] },
                apiKeyFetchedAt: Date.now(),
            })
            const list = vi.fn()
            if (failure === 'timeout') {
                list.mockRejectedValueOnce(new Error('Synthetic project-list timeout'))
            } else {
                list.mockResolvedValueOnce(
                    failure === 'empty'
                        ? { success: true, data: [] }
                        : { success: false, error: new Error('Synthetic project-list 503') }
                )
            }
            list.mockResolvedValue({ success: true, data: [{ id: 789 }] })
            let currentUser = mockUser
            const api = {
                config: { apiToken: 'phx_test' },
                users: () => ({ me: async () => ({ success: true, data: currentUser }) }),
                organizations: () => ({ projects: () => ({ list }) }),
                projects: () => ({
                    get: async () => ({
                        success: false,
                        error: new Error('Project metadata is outside the active org scope'),
                    }),
                }),
            } as unknown as ApiClient
            const first = new StateManager(cache, api, { pin: {}, sessionScoped: true }, sessionCache)
            await first.setDefaultOrganizationAndProject()
            currentUser = {
                ...mockUser,
                organization: { id: 'org-2', name: 'Org 2' },
                team: { id: 999, name: 'Other project', organization: 'org-2', timezone: 'UTC' },
            }
            const next = new StateManager(cache, api, { pin: {}, sessionScoped: true, orgId: 'org-3' }, sessionCache)

            expect(await next.getProjectId()).toBe('789')
        })

        it('keeps the first recovered default and a newer switch when a delayed recovery finishes', async () => {
            const sessionCache = new MemoryCache<SessionScopedState>('default-recovery-race')
            await sessionCache.clear()
            await sessionCache.set('defaultContext', { organizationId: 'org-3' })
            let requested!: () => void
            let finish!: () => void
            const started = new Promise<void>((resolve) => {
                requested = resolve
            })
            const gate = new Promise<void>((resolve) => {
                finish = resolve
            })
            const list = vi
                .fn()
                .mockImplementationOnce(async () => {
                    requested()
                    await gate
                    return { success: true, data: [{ id: 789 }] }
                })
                .mockResolvedValue({ success: true, data: [{ id: 999 }] })
            const api = {
                config: { apiToken: 'phx_test' },
                organizations: () => ({ projects: () => ({ list }) }),
            } as unknown as ApiClient
            const snapshot = (): PinnedActiveContext => ({ pin: {}, sessionScoped: true, orgId: 'org-3' })
            const older = new StateManager(cache, api, snapshot(), sessionCache)
            const newer = new StateManager(cache, api, snapshot(), sessionCache)
            const pending = older.setDefaultOrganizationAndProject()
            await started
            try {
                await newer.setDefaultOrganizationAndProject()
                await newer.setActiveContext({ orgId: 'org-2', projectId: '222' })
            } finally {
                finish()
            }

            expect({
                resolved: await pending,
                orgId: await sessionCache.get('activeOrgId'),
                projectId: await sessionCache.get('activeProjectId'),
            }).toEqual({
                resolved: { organizationId: 'org-3', projectId: 999 },
                orgId: 'org-2',
                projectId: '222',
            })
        })

        it('does not capture a 404 from the scoped-org projects lookup', async () => {
            // A misconfigured key pointed at a deleted or inaccessible org makes
            // the org-nested projects endpoint return 404 on every retry. This
            // is a recoverable user-config state, so it must not flood error
            // tracking — the agent recovers via switch-project/switch-organization.
            const scopedOrgApiKey = {
                ...mockApiKey,
                scoped_organizations: ['org-3'],
            }

            const mockApi = stateManager as any
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue(scopedOrgApiKey)
            vi.spyOn(stateManager, 'getUser').mockResolvedValue(mockUser)
            const reportSpy = vi.spyOn(stateManager as any, '_reportException').mockImplementation(() => {})

            mockApi._api = {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({
                            success: false,
                            error: new PostHogApiError({
                                status: 404,
                                statusText: 'Not Found',
                                body: '{"detail":"Organization not found."}',
                                url: 'https://app.posthog.com/api/organizations/org-3/projects/',
                                method: 'GET',
                            }),
                        }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBeUndefined()
            expect(reportSpy).not.toHaveBeenCalled()
        })
    })

    describe('getOrgID', () => {
        it('should return cached orgId if available', async () => {
            await cache.set('orgId', 'cached-org-id')

            const result = await stateManager.getOrgID()

            expect(result).toBe('cached-org-id')
        })

        it('should call setDefaultOrganizationAndProject when not cached', async () => {
            const spy = vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: 'default-org',
                projectId: 123,
            })

            const result = await stateManager.getOrgID()

            expect(result).toBe('default-org')
            expect(spy).toHaveBeenCalledOnce()
        })

        it('falls back to project.organization for team-scoped keys that omit orgId', async () => {
            // Mirrors the team-scoped path in `_getDefaultOrganizationAndProject`
            // which intentionally returns `{ projectId }` only — getOrgID should
            // recover via the cached project.
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: 456,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                uuid: 'uuid-456',
                name: 'My Project',
                organization: 'derived-org',
            } as any)

            const result = await stateManager.getOrgID()

            expect(result).toBe('derived-org')
        })

        it('caches the derived org id so repeat calls short-circuit', async () => {
            // Without this caching, every tool that calls getOrgID would re-hit
            // setDefaultOrganizationAndProject + getCachedOrFetchProject for a
            // team-scoped key.
            const setDefaultSpy = vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: 456,
            })
            const getProjectSpy = vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                uuid: 'uuid-456',
                name: 'My Project',
                organization: 'derived-org',
            } as any)

            const first = await stateManager.getOrgID()
            const second = await stateManager.getOrgID()

            expect(first).toBe('derived-org')
            expect(second).toBe('derived-org')
            expect(await cache.get('orgId')).toBe('derived-org')
            // Second call hits cache, not the resolver path.
            expect(setDefaultSpy).toHaveBeenCalledOnce()
            expect(getProjectSpy).toHaveBeenCalledOnce()
        })

        it('throws MissingOrganizationContextError when no org can be resolved', async () => {
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: undefined,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            await expect(stateManager.getOrgID()).rejects.toMatchObject({
                name: 'MissingOrganizationContextError',
                message: expect.stringContaining('switch-organization'),
            })
        })
    })

    describe('getCachedOrFetchOrg', () => {
        it('returns undefined when no org can be resolved (does not throw)', async () => {
            // Consent checks rely on this best-effort contract.
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue({
                scopes: ['organization:read'],
                scoped_organizations: [],
                scoped_teams: [],
            })
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: undefined,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
        })

        it('skips the org fetch when the API key lacks organization:read', async () => {
            // Pre-#58726 behaviour: every MCP session init with a project-scoped
            // personal API key would 403 on `/api/organizations/{id}/` and
            // dogpile error tracking. The scope guard short-circuits before the
            // HTTP call so no exception is captured and the org is treated as
            // best-effort missing.
            await cache.set('orgId', 'org-1')
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue({
                scopes: ['project:read', 'insight:read'],
                scoped_organizations: [],
                scoped_teams: [456],
            })
            const orgGet = vi.fn()
            ;(stateManager as any)._api = {
                organizations: () => ({ get: orgGet }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
            expect(orgGet).not.toHaveBeenCalled()
        })

        it.each([['organization:read'], ['*']])(
            'skips the org fetch for project-scoped API keys even when they carry %s',
            async (scope) => {
                await cache.set('orgId', 'org-1')
                vi.spyOn(stateManager, 'getApiKey').mockResolvedValue({
                    scopes: [scope],
                    scoped_organizations: [],
                    scoped_teams: [456],
                })
                const orgGet = vi.fn()
                ;(stateManager as any)._api = {
                    organizations: () => ({ get: orgGet }),
                }

                const result = await stateManager.getCachedOrFetchOrg()

                expect(result).toBeUndefined()
                expect(orgGet).not.toHaveBeenCalled()
            }
        )

        it('skips org resolution for project-scoped API keys', async () => {
            vi.spyOn(stateManager, 'getApiKey').mockResolvedValue({
                scopes: ['*'],
                scoped_organizations: [],
                scoped_teams: [456],
            })
            const setDefaultSpy = vi.spyOn(stateManager, 'setDefaultOrganizationAndProject')
            const getProjectSpy = vi.spyOn(stateManager, 'getCachedOrFetchProject')
            const orgGet = vi.fn()
            ;(stateManager as any)._api = {
                organizations: () => ({ get: orgGet }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
            expect(setDefaultSpy).not.toHaveBeenCalled()
            expect(getProjectSpy).not.toHaveBeenCalled()
            expect(orgGet).not.toHaveBeenCalled()
        })

        it.each([['organization:read'], ['organization:write'], ['*']])(
            'fetches the org when the API key carries %s',
            async (scope) => {
                await cache.set('orgId', 'org-1')
                vi.spyOn(stateManager, 'getApiKey').mockResolvedValue({
                    scopes: [scope],
                    scoped_organizations: [],
                    scoped_teams: [],
                })
                const orgGet = vi.fn().mockResolvedValue({
                    success: true,
                    data: { id: 'org-1', name: 'Org 1' },
                })
                ;(stateManager as any)._api = {
                    organizations: () => ({ get: orgGet }),
                }

                const result = await stateManager.getCachedOrFetchOrg()

                expect(orgGet).toHaveBeenCalledWith({ orgId: 'org-1' })
                expect(result).toMatchObject({ id: 'org-1', name: 'Org 1' })
            }
        )
    })

    describe('getAiConsentGiven', () => {
        it.each([
            [true, true],
            [false, false],
            [null, false],
        ])('returns consent from the fetched org when the org is resolvable (flag %s)', async (flag, expected) => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue({
                id: 'org-1',
                name: 'Org 1',
                is_ai_data_processing_approved: flag,
            } as any)
            const userSpy = vi.spyOn(stateManager, 'getCachedOrFetchUser')

            const result = await stateManager.getAiConsentGiven()

            expect(result).toBe(expected)
            expect(userSpy).not.toHaveBeenCalled()
        })

        it.each([
            [true, true],
            [false, false],
        ])(
            'falls back to users/@me consent when the org is unreachable and the current org owns the active project (flag %s)',
            async (flag, expected) => {
                // Team-scoped tokens (e.g. sandbox OAuth tokens) can never fetch
                // `/api/organizations/{id}/`, so getCachedOrFetchOrg yields undefined.
                vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
                vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({
                    ...mockUser,
                    organization: { id: 'org-1', name: 'Org 1', is_ai_data_processing_approved: flag },
                })
                vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                    id: 456,
                    organization: 'org-1',
                } as any)

                const result = await stateManager.getAiConsentGiven()

                expect(result).toBe(expected)
            }
        )

        it("returns undefined when the user's current org does not own the active project", async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({
                ...mockUser,
                organization: { id: 'org-other', name: 'Other Org', is_ai_data_processing_approved: true },
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                organization: 'org-1',
            } as any)

            const result = await stateManager.getAiConsentGiven()

            expect(result).toBeUndefined()
        })

        it('returns undefined when the user has no current org', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({ ...mockUser, organization: null })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                organization: 'org-1',
            } as any)

            const result = await stateManager.getAiConsentGiven()

            expect(result).toBeUndefined()
        })

        it('returns undefined when no project is resolvable', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({
                ...mockUser,
                organization: { id: 'org-1', name: 'Org 1', is_ai_data_processing_approved: true },
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getAiConsentGiven()

            expect(result).toBeUndefined()
        })

        it('returns undefined (fail closed) when the fallback fetches throw', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockRejectedValue(new Error('boom'))
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getAiConsentGiven()

            expect(result).toBeUndefined()
        })
    })

    describe('getAvailableFeatures', () => {
        it('returns available_product_features keys from the fetched org when the org is resolvable', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue({
                id: 'org-1',
                name: 'Org 1',
                available_product_features: [{ key: 'audit_logs' }, { key: 'sso' }],
            } as any)
            const userSpy = vi.spyOn(stateManager, 'getCachedOrFetchUser')

            const result = await stateManager.getAvailableFeatures()

            expect(result).toEqual(['audit_logs', 'sso'])
            expect(userSpy).not.toHaveBeenCalled()
        })

        it('returns an empty array (not undefined) when the org has no entitled features', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue({
                id: 'org-1',
                name: 'Org 1',
                available_product_features: [],
            } as any)
            const userSpy = vi.spyOn(stateManager, 'getCachedOrFetchUser')

            const result = await stateManager.getAvailableFeatures()

            expect(result).toEqual([])
            expect(userSpy).not.toHaveBeenCalled()
        })

        it('treats a null available_product_features from the fetched org as no features, not a fallback trigger', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue({
                id: 'org-1',
                name: 'Org 1',
                available_product_features: null,
            } as any)
            const userSpy = vi.spyOn(stateManager, 'getCachedOrFetchUser')

            const result = await stateManager.getAvailableFeatures()

            expect(result).toEqual([])
            expect(userSpy).not.toHaveBeenCalled()
        })

        it('falls back to users/@me features when the org is unreachable and the current org owns the active project', async () => {
            // Team-scoped tokens (e.g. sandbox OAuth tokens) can never fetch
            // `/api/organizations/{id}/`, so getCachedOrFetchOrg yields undefined.
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({
                ...mockUser,
                organization: {
                    id: 'org-1',
                    name: 'Org 1',
                    available_product_features: [{ key: 'audit_logs' }],
                },
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                organization: 'org-1',
            } as any)

            const result = await stateManager.getAvailableFeatures()

            expect(result).toEqual(['audit_logs'])
        })

        it('returns undefined when the org has no readable entitlements and no fallback applies', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockResolvedValue({
                ...mockUser,
                organization: { id: 'org-other', name: 'Other Org' },
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                organization: 'org-1',
            } as any)

            const result = await stateManager.getAvailableFeatures()

            expect(result).toBeUndefined()
        })

        it('returns undefined (fail open) when the fallback fetches throw', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchOrg').mockResolvedValue(undefined)
            vi.spyOn(stateManager, 'getCachedOrFetchUser').mockRejectedValue(new Error('boom'))
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getAvailableFeatures()

            expect(result).toBeUndefined()
        })
    })

    describe('getProjectId', () => {
        it('should return cached projectId if available', async () => {
            await cache.set('projectId', 'cached-project-id')

            const result = await stateManager.getProjectId()

            expect(result).toBe('cached-project-id')
        })

        it('should call setDefaultOrganizationAndProject when not cached', async () => {
            const spy = vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: 'default-org',
                projectId: 789,
            })

            const result = await stateManager.getProjectId()

            expect(result).toBe('789')
            expect(spy).toHaveBeenCalledOnce()
        })

        it('throws MissingProjectContextError when no default project can be resolved', async () => {
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: 'org-only',
                projectId: undefined,
            })

            await expect(stateManager.getProjectId()).rejects.toMatchObject({
                name: 'MissingProjectContextError',
                organizationId: 'org-only',
                message: expect.stringContaining('switch-project'),
            })
        })
    })

    describe('getOrFetchCached (via getOrFetchGroupTypes)', () => {
        const projectId = '42'

        it('should fetch and cache on first call', async () => {
            const mockGroupTypes = [{ group_type: 'company', group_type_index: 0 }]
            const mockApi = stateManager as any
            mockApi._api = {
                getGroupTypes: vi.fn().mockResolvedValue(mockGroupTypes),
            }

            const result = await stateManager.getOrFetchGroupTypes(projectId)

            expect(result).toEqual(mockGroupTypes)
            expect(await cache.get(`groupTypes:${projectId}` as any)).toEqual(mockGroupTypes)
            expect(await cache.get(`groupTypesFetchedAt:${projectId}` as any)).toEqual(expect.any(Number))
        })

        it('should return cached value without re-fetching when not stale', async () => {
            const mockGroupTypes = [{ group_type: 'company', group_type_index: 0 }]
            await cache.set(`groupTypes:${projectId}` as any, mockGroupTypes as any)
            await cache.set(`groupTypesFetchedAt:${projectId}` as any, Date.now() as any)

            const getGroupTypes = vi.fn()
            const mockApi = stateManager as any
            mockApi._api = { getGroupTypes }

            const result = await stateManager.getOrFetchGroupTypes(projectId)

            expect(result).toEqual(mockGroupTypes)
            expect(getGroupTypes).not.toHaveBeenCalled()
        })

        it('should not retry a failed fetch within the cache TTL (negative caching)', async () => {
            const getGroupTypes = vi.fn().mockRejectedValue(new Error('API error'))
            const mockApi = stateManager as any
            mockApi._api = { getGroupTypes }

            const first = await stateManager.getOrFetchGroupTypes(projectId)
            expect(first).toBeUndefined()
            expect(getGroupTypes).toHaveBeenCalledOnce()

            const second = await stateManager.getOrFetchGroupTypes(projectId)
            expect(second).toBeUndefined()
            expect(getGroupTypes).toHaveBeenCalledOnce()
        })

        it('should retry after the cache TTL expires', async () => {
            const getGroupTypes = vi.fn().mockRejectedValue(new Error('API error'))
            const mockApi = stateManager as any
            mockApi._api = { getGroupTypes }

            await stateManager.getOrFetchGroupTypes(projectId)
            expect(getGroupTypes).toHaveBeenCalledOnce()

            await cache.set(`groupTypesFetchedAt:${projectId}` as any, (Date.now() - 11 * 60 * 1000) as any)

            await stateManager.getOrFetchGroupTypes(projectId)
            expect(getGroupTypes).toHaveBeenCalledTimes(2)
        })

        it('should return undefined (not stale data) when fetch succeeds then later fails', async () => {
            const mockGroupTypes = [{ group_type: 'company', group_type_index: 0 }]
            const getGroupTypes = vi
                .fn()
                .mockResolvedValueOnce(mockGroupTypes)
                .mockRejectedValueOnce(new Error('API error'))
            const mockApi = stateManager as any
            mockApi._api = { getGroupTypes }

            const first = await stateManager.getOrFetchGroupTypes(projectId)
            expect(first).toEqual(mockGroupTypes)

            await cache.set(`groupTypesFetchedAt:${projectId}` as any, (Date.now() - 11 * 60 * 1000) as any)

            const second = await stateManager.getOrFetchGroupTypes(projectId)
            expect(second).toEqual(mockGroupTypes)
        })

        // A project without events is re-read after a minute so the no-data notice stops soon
        // after the first event. A project with events never flips back, so it keeps the long TTL.
        it.each([
            ['without events is re-read', false, 2],
            ['with events stays cached', true, 1],
        ])('a project %s two minutes after the fetch', async (_name, ingestedEvent, expectedFetches) => {
            await cache.set('projectId', projectId)
            const get = vi.fn().mockResolvedValue({ success: true, data: { id: 42, ingested_event: ingestedEvent } })
            ;(stateManager as any)._api = { projects: () => ({ get }) }

            await stateManager.getCachedOrFetchProject()
            await cache.set(`cachedProjectFetchedAt:${projectId}`, Date.now() - 2 * 60 * 1000)
            await stateManager.getCachedOrFetchProject()

            expect(get).toHaveBeenCalledTimes(expectedFetches)
        })
    })

    describe('getOrFetchHasWarehouseData', () => {
        const projectId = '42'
        const warehouseScopes = ['warehouse_table:read', 'external_data_source:read']
        const rejected = new Error('Synthetic list failure')

        it.each<[string, string[], unknown[], boolean | undefined, number?]>([
            ['unknown without a warehouse read scope', ['query:read'], [], undefined],
            ['unknown when the only readable list is empty', ['warehouse_table:read'], [{ count: 0 }], undefined],
            ['true when the only readable list has a table', ['warehouse_table:read'], [{ count: 1 }], true],
            ['unknown when the refresh of an empty answer fails', warehouseScopes, [rejected, rejected], undefined, 0],
            ['true when a table exists', warehouseScopes, [{ count: 1 }, { count: 0 }], true],
            ['true when only a source exists', warehouseScopes, [{ count: 0 }, { count: 2 }], true],
            ['false when both lists are empty', warehouseScopes, [{ count: 0 }, { count: 0 }], false],
            ['unknown when a list fails and the other is empty', warehouseScopes, [{ count: 0 }, rejected], undefined],
            ['true when a list fails and the other has a table', warehouseScopes, [{ count: 1 }, rejected], true],
        ])('is %s', async (_name, scopes, responses, expected, staleCount) => {
            await cache.set('apiKey', { scopes, scoped_organizations: [], scoped_teams: [] })
            if (staleCount !== undefined) {
                await cache.set(`warehouseObjectCount:${projectId}`, staleCount)
                await cache.set(`warehouseObjectCountFetchedAt:${projectId}`, Date.now() - 2 * 60 * 1000)
            }
            const request = vi.fn()
            for (const response of responses) {
                if (response instanceof Error) {
                    request.mockRejectedValueOnce(response)
                } else {
                    request.mockResolvedValueOnce(response)
                }
            }
            ;(stateManager as any)._api = { config: { apiToken: 'phx_test' }, request }

            expect(await stateManager.getOrFetchHasWarehouseData(projectId)).toBe(expected)
            expect(request).toHaveBeenCalledTimes(responses.length)
        })
    })

    describe('getOrFetchIntegrationKinds', () => {
        const projectId = '42'

        it('returns undefined without calling the API when the key lacks integration:read', async () => {
            await cache.set('apiKey', { scopes: ['project:read'], scoped_organizations: [], scoped_teams: [] })
            const request = vi.fn()
            ;(stateManager as any)._api = { config: { apiToken: 'phx_test' }, request }

            const result = await stateManager.getOrFetchIntegrationKinds(projectId)

            expect(result).toBeUndefined()
            expect(request).not.toHaveBeenCalled()
        })

        it('fetches, dedupes, and sorts integration kinds when the scope is present', async () => {
            await cache.set('apiKey', { scopes: ['integration:read'], scoped_organizations: [], scoped_teams: [] })
            const request = vi.fn().mockResolvedValue({
                results: [{ kind: 'slack' }, { kind: 'github' }, { kind: 'github' }],
            })
            ;(stateManager as any)._api = { config: { apiToken: 'phx_test' }, request }

            const result = await stateManager.getOrFetchIntegrationKinds(projectId)

            expect(result).toEqual(['github', 'slack'])
            expect(request).toHaveBeenCalledWith(
                expect.objectContaining({ method: 'GET', path: `/api/projects/${projectId}/integrations/` })
            )
        })
    })

    describe('getAnalyticsContext', () => {
        it('returns organization, project, UUID, and name from the cached project', async () => {
            await cache.set('orgId', 'org-1')
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                uuid: 'project-uuid-456',
                name: 'My Project',
                organization: 'org-1',
                ingested_event: false,
            } as any)

            const result = await stateManager.getAnalyticsContext()

            expect(result).toEqual({
                organizationId: 'org-1',
                projectId: '456',
                projectUuid: 'project-uuid-456',
                projectName: 'My Project',
                projectHasData: false,
            })
        })

        it('falls back to project.organization when orgId is not yet cached', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                uuid: 'project-uuid-456',
                name: 'My Project',
                organization: 'org-2',
            } as any)

            const result = await stateManager.getAnalyticsContext()

            expect(result).toEqual({
                organizationId: 'org-2',
                projectId: '456',
                projectUuid: 'project-uuid-456',
                projectName: 'My Project',
            })
        })

        it('omits project fields when no project is cached or fetchable', async () => {
            await cache.set('orgId', 'org-1')
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getAnalyticsContext()

            expect(result).toEqual({ organizationId: 'org-1' })
        })

        it('returns empty object when neither org nor project is available', async () => {
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getAnalyticsContext()

            expect(result).toEqual({})
        })
    })
})
