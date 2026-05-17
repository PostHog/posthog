import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { PostHogPermissionError } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'
import type { ApiRedactedPersonalApiKey, ApiUser } from '@/schema/api'
import type { State } from '@/tools/types'

const captureException = vi.fn()
vi.mock('@/lib/analytics', () => ({
    getPostHogClient: () => ({
        captureException,
        capture: vi.fn(),
    }),
    AnalyticsEvent: {},
    isFeatureFlagEnabled: vi.fn().mockResolvedValue(false),
}))

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
        captureException.mockClear()
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
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: undefined,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            const result = await stateManager.getCachedOrFetchOrg()

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

    describe('permission-error stash during cached state fetches', () => {
        // Mirrors what the API client throws for a personal API key that lacks
        // `organization:read` on `/api/organizations/{orgId}/`.
        const orgPermissionError = new PostHogPermissionError({
            detail: "API key missing required scope 'organization:read'",
            missingScope: 'organization:read',
            url: 'https://us.posthog.com/api/organizations/org-1/',
            method: 'GET',
        })
        const projectPermissionError = new PostHogPermissionError({
            detail: "API key missing required scope 'project:read'",
            missingScope: 'project:read',
            url: 'https://us.posthog.com/api/projects/456/',
            method: 'GET',
        })

        it('stashes a PostHogPermissionError from the org fetcher without capturing it', async () => {
            await cache.set('orgId', 'org-1')
            ;(stateManager as any)._api = {
                organizations: () => ({
                    get: vi.fn().mockResolvedValue({ success: false, error: orgPermissionError }),
                }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
            expect((stateManager as any)._pendingPermissionErrors.get('org')).toBe(orgPermissionError)
            expect(captureException).not.toHaveBeenCalled()
        })

        it('stashes a PostHogPermissionError from the project fetcher without capturing it', async () => {
            await cache.set('projectId', '456')
            ;(stateManager as any)._api = {
                projects: () => ({
                    get: vi.fn().mockResolvedValue({ success: false, error: projectPermissionError }),
                }),
            }

            const result = await stateManager.getCachedOrFetchProject()

            expect(result).toBeUndefined()
            expect((stateManager as any)._pendingPermissionErrors.get('project')).toBe(projectPermissionError)
            expect(captureException).not.toHaveBeenCalled()
        })

        it('still captures non-permission errors to error tracking', async () => {
            await cache.set('orgId', 'org-1')
            const otherError = new Error('network blew up')
            ;(stateManager as any)._api = {
                organizations: () => ({
                    get: vi.fn().mockResolvedValue({ success: false, error: otherError }),
                }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
            expect((stateManager as any)._pendingPermissionErrors.has('org')).toBe(false)
            expect(captureException).toHaveBeenCalledWith(otherError, undefined, {
                tag: 'mcp',
                team: 'posthog_ai',
                context: 'get_or_fetch_org',
            })
        })

        it('captures permission errors without a missingScope (e.g. revoked access) on org/project fetchers', async () => {
            // Suppression is intentionally narrow: only `PostHogPermissionError`
            // instances with a parsed `missingScope` are stashed and skipped.
            // 403s without a missingScope — revoked access, policy denial,
            // backend error-format drift — are not expected user state and
            // should keep their telemetry signal.
            const accessRevokedError = new PostHogPermissionError({
                detail: 'API key does not have access to the requested organization: ID org-1.',
                url: 'https://us.posthog.com/api/organizations/org-1/',
                method: 'GET',
            })
            await cache.set('orgId', 'org-1')
            ;(stateManager as any)._api = {
                organizations: () => ({
                    get: vi.fn().mockResolvedValue({ success: false, error: accessRevokedError }),
                }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toBeUndefined()
            expect((stateManager as any)._pendingPermissionErrors.has('org')).toBe(false)
            expect(captureException).toHaveBeenCalledWith(accessRevokedError, undefined, {
                tag: 'mcp',
                team: 'posthog_ai',
                context: 'get_or_fetch_org',
            })
        })

        it('clears the stash when a later fetch succeeds', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('org', orgPermissionError)
            await cache.set('orgId', 'org-1')
            ;(stateManager as any)._api = {
                organizations: () => ({
                    get: vi.fn().mockResolvedValue({ success: true, data: { name: 'Org 1' } }),
                }),
            }

            const result = await stateManager.getCachedOrFetchOrg()

            expect(result).toEqual({ name: 'Org 1' })
            expect((stateManager as any)._pendingPermissionErrors.has('org')).toBe(false)
        })

        it('captures permission errors from fetchers we do not surface lazily', async () => {
            // `group_types` is not in PENDING_PERMISSION_KEYS — a permission
            // error there should still be captured to error tracking, not
            // silently swallowed by the same branch that catches `org`/`project`.
            const groupTypesPermissionError = new PostHogPermissionError({
                detail: "API key missing required scope 'group:read'",
                missingScope: 'group:read',
                url: 'https://us.posthog.com/api/projects/456/groups_types/',
                method: 'GET',
            })
            ;(stateManager as any)._api = {
                getGroupTypes: vi.fn().mockRejectedValue(groupTypesPermissionError),
            }

            const result = await stateManager.getOrFetchGroupTypes('456')

            expect(result).toBeUndefined()
            expect((stateManager as any)._pendingPermissionErrors.has('group_types')).toBe(false)
            expect(captureException).toHaveBeenCalledWith(groupTypesPermissionError, undefined, {
                tag: 'mcp',
                team: 'posthog_ai',
                context: 'get_or_fetch_group_types',
            })
        })
    })

    describe('getOrgID with a pending permission error', () => {
        const orgPermissionError = new PostHogPermissionError({
            detail: "API key missing required scope 'organization:read'",
            missingScope: 'organization:read',
            url: 'https://us.posthog.com/api/organizations/org-1/',
            method: 'GET',
        })

        it('throws the stashed permission error when no org can be resolved from any source', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('org', orgPermissionError)
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: undefined,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            await expect(stateManager.getOrgID()).rejects.toBe(orgPermissionError)
        })

        it('does not throw the stashed error when an org id is already cached', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('org', orgPermissionError)
            await cache.set('orgId', 'cached-org')

            const result = await stateManager.getOrgID()

            expect(result).toBe('cached-org')
        })

        it('does not throw the stashed error when an org is derivable from the cached project', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('org', orgPermissionError)
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

        it('surfaces a project-keyed permission error when the org derives via project and that fetch failed', async () => {
            // `_resolveOrganizationId` falls back to `getCachedOrFetchProject` for
            // team-scoped keys. If that fetch hit a permission error, only the
            // `'project'` key is stashed. `getOrgID` should still surface a
            // scope-specific message rather than the generic "no org selected".
            const projectPermissionError = new PostHogPermissionError({
                detail: "API key missing required scope 'project:read'",
                missingScope: 'project:read',
                url: 'https://us.posthog.com/api/projects/456/',
                method: 'GET',
            })
            ;(stateManager as any)._pendingPermissionErrors.set('project', projectPermissionError)
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: undefined,
                projectId: undefined,
            })
            vi.spyOn(stateManager, 'getCachedOrFetchProject').mockResolvedValue(undefined)

            await expect(stateManager.getOrgID()).rejects.toBe(projectPermissionError)
        })
    })

    describe('getProjectId with a pending permission error', () => {
        const projectPermissionError = new PostHogPermissionError({
            detail: "API key missing required scope 'project:read'",
            missingScope: 'project:read',
            url: 'https://us.posthog.com/api/projects/456/',
            method: 'GET',
        })

        it('throws the stashed permission error when no project can be resolved', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('project', projectPermissionError)
            vi.spyOn(stateManager, 'setDefaultOrganizationAndProject').mockResolvedValue({
                organizationId: 'org-only',
                projectId: undefined,
            })

            await expect(stateManager.getProjectId()).rejects.toBe(projectPermissionError)
        })

        it('does not throw the stashed error when a project id is already cached', async () => {
            ;(stateManager as any)._pendingPermissionErrors.set('project', projectPermissionError)
            await cache.set('projectId', '999')

            const result = await stateManager.getProjectId()

            expect(result).toBe('999')
        })
    })
})
