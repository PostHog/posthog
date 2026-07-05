import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import switchOrganizationTool from '@/tools/organizations/setActive'
import switchProjectTool from '@/tools/projects/setActive'
import type { CachedOrg, CachedProject, Context, State } from '@/tools/types'

type FakeProject = Pick<CachedProject, 'id' | 'organization' | 'name'>
type FakeOrg = Pick<CachedOrg, 'id' | 'name'>

interface FakeWorld {
    projects?: Record<string, FakeProject>
    orgs?: Record<string, FakeOrg>
    orgProjects?: Record<string, FakeProject[]>
}

// switch-project / switch-organization only touch `context.cache` and `context.api`, so a
// small in-memory fake of those two is enough to exercise the org/project reconciliation
// without a live PostHog API.
function makeContext(world: FakeWorld): {
    context: Context
    listCalls: string[]
} {
    const cache = new MemoryCache<State>(`switch-env-${Math.random()}`)
    const listCalls: string[] = []
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
                const org = world.orgs?.[orgId]
                return org
                    ? { success: true as const, data: org as CachedOrg }
                    : { success: false as const, error: new Error('org not found') }
            },
            projects: ({ orgId }: { orgId: string }) => ({
                list: async () => {
                    listCalls.push(orgId)
                    return { success: true as const, data: (world.orgProjects?.[orgId] ?? []) as CachedProject[] }
                },
            }),
        }),
    } as unknown as ApiClient

    const context = {
        api,
        cache,
        env: {} as any,
        stateManager: {} as any,
        sessionManager: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context

    return { context, listCalls }
}

describe('switch active environment', () => {
    beforeEach(() => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    describe('switch-project', () => {
        const tool = switchProjectTool()

        it('repoints the active org to the switched project parent org', async () => {
            const { context } = makeContext({
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

        it('falls back to the cached org when the project fetch fails', async () => {
            const { context } = makeContext({
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
            const { context, listCalls } = makeContext({
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
            const { context, listCalls } = makeContext({
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

        it('clears the stale project when the org has no accessible projects', async () => {
            const { context } = makeContext({
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
