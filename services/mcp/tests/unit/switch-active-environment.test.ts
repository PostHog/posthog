import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { StateManager } from '@/lib/StateManager'
import switchOrganizationTool from '@/tools/organizations/setActive'
import switchProjectTool from '@/tools/projects/setActive'
import type { CachedOrg, CachedProject, Context, State } from '@/tools/types'

type FakeProject = Pick<CachedProject, 'id' | 'organization' | 'name'> &
    Partial<Pick<CachedProject, 'person_on_events_querying_enabled'>>
type FakeOrg = Pick<CachedOrg, 'id' | 'name'>

interface FakeWorld {
    projects?: Record<string, FakeProject>
    orgs?: Record<string, FakeOrg>
    orgProjects?: Record<string, FakeProject[]>
    failingOrgProjectLists?: string[]
    apiKey?: NonNullable<State['apiKey']>
}

// switch-project / switch-organization only touch the cache, the API client and the state
// manager's org resolution, so a small in-memory fake of the API plus the real state manager
// is enough to exercise the org/project reconciliation without a live PostHog API.
async function makeContext(world: FakeWorld): Promise<{
    context: Context
    listCalls: string[]
    orgGetCalls: string[]
}> {
    const cache = new MemoryCache<State>(`switch-env-${Math.random()}`)
    const listCalls: string[] = []
    const orgGetCalls: string[] = []
    const api = {
        publicBaseUrl: 'https://us.posthog.com',
        projects: () => ({
            get: async ({ projectId }: { projectId: string }) => {
                const project = world.projects?.[projectId]
                return project
                    ? { success: true as const, data: project as CachedProject }
                    : { success: false as const, error: new Error('project not found') }
            },
        }),
        organizations: () => ({
            get: async ({ orgId }: { orgId: string }) => {
                orgGetCalls.push(orgId)
                const org = world.orgs?.[orgId]
                return org
                    ? { success: true as const, data: org as CachedOrg }
                    : { success: false as const, error: new Error('org not found') }
            },
            projects: ({ orgId }: { orgId: string }) => ({
                list: async () => {
                    listCalls.push(orgId)
                    if (world.failingOrgProjectLists?.includes(orgId)) {
                        return { success: false as const, error: new Error('projects list failed') }
                    }
                    return { success: true as const, data: (world.orgProjects?.[orgId] ?? []) as CachedProject[] }
                },
            }),
        }),
    } as unknown as ApiClient

    // The org resolution goes through StateManager, so use the real one over the fake API
    // and pre-seed the key it reads for the scoped-token guard.
    await cache.set('apiKey', world.apiKey ?? { scopes: ['*'], scoped_teams: [], scoped_organizations: [] })

    const context = {
        api,
        cache,
        env: {} as any,
        stateManager: new StateManager(cache, api),
        sessionManager: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context

    return { context, listCalls, orgGetCalls }
}

describe('switch active environment', () => {
    beforeEach(() => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    describe('switch-project', () => {
        const tool = switchProjectTool()

        it('repoints the active org to the switched project parent org', async () => {
            const { context } = await makeContext({
                projects: { '99': { id: 99, organization: 'org-b', name: 'B Project' } },
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
            })
            // Session starts anchored to a different org.
            await context.cache.set('orgId', 'org-a')
            await context.cache.set('cachedOrg:org-a' as const, { id: 'org-a', name: 'Org A' } as CachedOrg)

            const result = await tool.handler(context, { projectId: 99 })

            expect(await context.cache.get('orgId')).toBe('org-b')
            const text = result.content[0]!.text
            expect(text).toContain('Org B')
            expect(text).not.toContain('Org A')
        })

        it('skips the organization fetch for a project-scoped token', async () => {
            const { context, orgGetCalls } = await makeContext({
                projects: { '99': { id: 99, organization: 'org-b', name: 'B Project' } },
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                apiKey: { scopes: ['project:read'], scoped_teams: [99], scoped_organizations: [] },
            })

            const result = await tool.handler(context, { projectId: 99 })

            // The org detail endpoint is not project-nested and the backend rejects it for
            // project-scoped keys, so the switch must not spend a round-trip on it.
            expect(orgGetCalls).toEqual([])
            expect(await context.cache.get('orgId')).toBe('org-b')
            expect(result.content[0]!.text).toContain('B Project')
        })

        it('falls back to the cached org when the project fetch fails', async () => {
            const { context } = await makeContext({
                orgs: { 'org-a': { id: 'org-a', name: 'Org A' } },
            })
            await context.cache.set('orgId', 'org-a')
            await context.cache.set('cachedOrg:org-a' as const, { id: 'org-a', name: 'Org A' } as CachedOrg)

            const result = await tool.handler(context, { projectId: 12345 })

            // No project org to reconcile to, so the previous org is preserved rather than lost.
            expect(await context.cache.get('orgId')).toBe('org-a')
            expect(result.content[0]!.text).toContain('Switched to project 12345')
        })
    })

    describe('switch-organization', () => {
        const tool = switchOrganizationTool()

        it('repoints the active project when it belongs to a different org', async () => {
            const { context, listCalls } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                orgProjects: { 'org-b': [{ id: 20, organization: 'org-b', name: 'B Project' }] },
            })
            await context.cache.set('projectId', '10')
            await context.cache.set(
                'cachedProject:10' as const,
                {
                    id: 10,
                    organization: 'org-a',
                    name: 'A Project',
                } as CachedProject
            )

            await tool.handler(context, { orgId: 'org-b' })

            expect(await context.cache.get('orgId')).toBe('org-b')
            expect(await context.cache.get('projectId')).toBe('20')
            expect(listCalls).toEqual(['org-b'])
        })

        it('keeps the active project when it already belongs to the selected org', async () => {
            const { context, listCalls } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
            })
            await context.cache.set('projectId', '10')
            await context.cache.set(
                'cachedProject:10' as const,
                {
                    id: 10,
                    organization: 'org-b',
                    name: 'B Project',
                } as CachedProject
            )

            await tool.handler(context, { orgId: 'org-b' })

            expect(await context.cache.get('projectId')).toBe('10')
            // No re-point needed, so we must not spend an extra projects-list round-trip.
            expect(listCalls).toEqual([])
        })

        it('keeps the active project when only the detail lookup failed and the org list still has it', async () => {
            const { context } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                orgProjects: {
                    'org-b': [
                        { id: 20, organization: 'org-b', name: 'First Project' },
                        { id: 10, organization: 'org-b', name: 'B Project' },
                    ],
                },
            })
            // Nothing cached for project 10 and its detail fetch fails, so membership can only
            // be answered by the org's project list.
            await context.cache.set('projectId', '10')

            const result = await tool.handler(context, { orgId: 'org-b' })

            expect(await context.cache.get('projectId')).toBe('10')
            expect(result.content[0]!.text).toContain('B Project')
        })

        it('keeps the active project when the org project list fails', async () => {
            const { context } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                failingOrgProjectLists: ['org-b'],
            })
            await context.cache.set('projectId', '10')
            await context.cache.set(
                'cachedProject:10' as const,
                {
                    id: 10,
                    organization: 'org-a',
                    name: 'A Project',
                } as CachedProject
            )

            const result = await tool.handler(context, { orgId: 'org-b' })

            // A failed list is not an empty org, so the selected project survives it.
            expect(await context.cache.get('projectId')).toBe('10')
            expect(result.content[0]!.text).not.toContain('A Project')
        })

        it('reports the repointed project person-properties mode from its detail response', async () => {
            const { context } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                // The org projects list is served by a basic serializer, so its rows carry no
                // `person_on_events_querying_enabled`; only the project detail response does.
                orgProjects: { 'org-b': [{ id: 20, organization: 'org-b', name: 'B Project' }] },
                projects: {
                    '20': {
                        id: 20,
                        organization: 'org-b',
                        name: 'B Project',
                        person_on_events_querying_enabled: true,
                    },
                },
            })
            await context.cache.set('projectId', '10')
            await context.cache.set(
                'cachedProject:10' as const,
                { id: 10, organization: 'org-a', name: 'A Project' } as CachedProject
            )

            const result = await tool.handler(context, { orgId: 'org-b' })

            expect(result.content[0]!.text).toContain('Person-on-events mode is enabled')
        })

        it('clears the stale project when the org has no accessible projects', async () => {
            const { context } = await makeContext({
                orgs: { 'org-b': { id: 'org-b', name: 'Org B' } },
                orgProjects: { 'org-b': [] },
            })
            await context.cache.set('projectId', '10')
            await context.cache.set(
                'cachedProject:10' as const,
                {
                    id: 10,
                    organization: 'org-a',
                    name: 'A Project',
                } as CachedProject
            )

            await tool.handler(context, { orgId: 'org-b' })

            expect(await context.cache.get('projectId')).toBeUndefined()
        })
    })
})
