import { describe, expect, it } from 'vitest'

import { findProjectsHandler } from '@/tools/projects/findProjects'
import type { Context } from '@/tools/types'

function createContext(orgs: { list: () => Promise<any>; projectsByOrg: Record<string, () => Promise<any>> }): Context {
    return {
        api: {
            organizations: () => ({
                list: orgs.list,
                projects: ({ orgId }: { orgId: string }) => ({
                    list: orgs.projectsByOrg[orgId] ?? (async () => ({ success: true, data: [] })),
                }),
            }),
        } as any,
        stateManager: {} as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const ok = (data: unknown) => async () => ({ success: true, data })
const fail = (message: string) => async () => ({ success: false, error: { message } })

describe('projects-find handler', () => {
    it('aggregates matching projects across every organization', async () => {
        const context = createContext({
            list: ok([
                { id: 'org-a', name: 'Org A' },
                { id: 'org-b', name: 'Org B' },
            ]),
            projectsByOrg: {
                'org-a': ok([{ id: 1, name: 'Marketing site' }]),
                'org-b': ok([{ id: 2, name: 'Marketing app' }]),
            },
        })

        const result = await findProjectsHandler(context, { name: 'marketing' })

        expect(result).toEqual([
            { id: 1, name: 'Marketing site', organization: 'org-a', organization_name: 'Org A' },
            { id: 2, name: 'Marketing app', organization: 'org-b', organization_name: 'Org B' },
        ])
    })

    it('matches the name filter case-insensitively and drops non-matches', async () => {
        const context = createContext({
            list: ok([{ id: 'org-a', name: 'Org A' }]),
            projectsByOrg: {
                'org-a': ok([
                    { id: 1, name: 'Checkout' },
                    { id: 2, name: 'Billing' },
                ]),
            },
        })

        const result = await findProjectsHandler(context, { name: 'CHECK' })

        expect(result).toEqual([{ id: 1, name: 'Checkout', organization: 'org-a', organization_name: 'Org A' }])
    })

    it('returns every project when no name filter is given', async () => {
        const context = createContext({
            list: ok([{ id: 'org-a', name: 'Org A' }]),
            projectsByOrg: {
                'org-a': ok([
                    { id: 1, name: 'Checkout' },
                    { id: 2, name: 'Billing' },
                ]),
            },
        })

        const result = await findProjectsHandler(context, {})

        expect(result.map((p) => p.id)).toEqual([1, 2])
    })

    it('skips organizations whose project list fails instead of failing the whole search', async () => {
        const context = createContext({
            list: ok([
                { id: 'org-a', name: 'Org A' },
                { id: 'org-b', name: 'Org B' },
            ]),
            projectsByOrg: {
                'org-a': fail('403 forbidden'),
                'org-b': ok([{ id: 2, name: 'Billing' }]),
            },
        })

        const result = await findProjectsHandler(context, {})

        expect(result).toEqual([{ id: 2, name: 'Billing', organization: 'org-b', organization_name: 'Org B' }])
    })

    it('throws when the organization list itself fails', async () => {
        const context = createContext({ list: fail('500 server error'), projectsByOrg: {} })

        await expect(findProjectsHandler(context, {})).rejects.toThrow('Failed to list organizations: 500 server error')
    })
})
