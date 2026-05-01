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
