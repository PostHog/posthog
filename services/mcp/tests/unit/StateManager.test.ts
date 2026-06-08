import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { StateManager } from '@/lib/StateManager'
import type { ApiRedactedPersonalApiKey, ApiUser } from '@/schema/api'
import type { State } from '@/tools/types'

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

    describe('getUser', () => {
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
                            data: [789],
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

        it('returns the org alone when the projects fetch fails', async () => {
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
                            success: false,
                            error: new Error('Projects fetch failed'),
                        }),
                    }),
                }),
            }

            const result = await stateManager.setDefaultOrganizationAndProject()

            expect(result.organizationId).toBe('org-3')
            expect(result.projectId).toBeUndefined()
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
            // Preserves the best-effort contract used by getEnvironmentPrompt and
            // consent checks: if no org is in scope, the call is a no-op.
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
    })

    describe('getAnalyticsContext', () => {
        it('returns organization, project, UUID, and name from the cached project', async () => {
            await cache.set('orgId', 'org-1')
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue({
                id: 456,
                uuid: 'project-uuid-456',
                name: 'My Project',
                organization: 'org-1',
            } as any)

            const result = await stateManager.getAnalyticsContext()

            expect(result).toEqual({
                organizationId: 'org-1',
                projectId: '456',
                projectUuid: 'project-uuid-456',
                projectName: 'My Project',
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
