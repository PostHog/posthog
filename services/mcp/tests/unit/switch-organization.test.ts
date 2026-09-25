import { describe, expect, it, vi } from 'vitest'

import setActiveOrganizationTool from '@/tools/organizations/setActive'
import type { Context } from '@/tools/types'

function createContext(organizationGet: ReturnType<typeof vi.fn>): {
    context: Context
    cache: Map<string, unknown>
    setSessionActiveContext: ReturnType<typeof vi.fn>
} {
    const cache = new Map<string, unknown>([['orgId', 'current-org']])
    const setSessionActiveContext = vi.fn().mockResolvedValue(undefined)
    const context = {
        api: {
            publicBaseUrl: 'https://us.posthog.com',
            organizations: () => ({ get: organizationGet }),
        },
        cache: {
            get: async (key: string) => cache.get(key),
            set: async (key: string, value: unknown) => {
                cache.set(key, value)
            },
        },
        stateManager: { getOrFetchIntegrationKinds: vi.fn().mockResolvedValue(undefined) },
        setSessionActiveContext,
    } as unknown as Context
    return { context, cache, setSessionActiveContext }
}

describe('switch-organization', () => {
    const tool = setActiveOrganizationTool()

    it('rejects an unreachable organization without changing the cached or pinned session', async () => {
        const apiError = new Error('404')
        const organizationGet = vi.fn().mockResolvedValue({ success: false, error: apiError })
        const { context, cache, setSessionActiveContext } = createContext(organizationGet)

        await expect(tool.handler(context, { orgId: 'missing-org' })).rejects.toMatchObject({
            message: expect.stringContaining('Could not switch to organization missing-org'),
            cause: apiError,
        })
        expect(cache.get('orgId')).toBe('current-org')
        expect(setSessionActiveContext).not.toHaveBeenCalled()
    })

    it('commits a reachable organization to the cache and pinned session', async () => {
        const organization = { id: 'new-org', name: 'New organization' }
        const organizationGet = vi.fn().mockResolvedValue({ success: true, data: organization })
        const { context, cache, setSessionActiveContext } = createContext(organizationGet)

        const result = await tool.handler(context, { orgId: 'new-org' })

        expect(result.content[0]!.text).toContain('Switched to organization new-org')
        expect(cache.get('orgId')).toBe('new-org')
        expect(cache.get('cachedOrg:new-org')).toEqual(organization)
        expect(setSessionActiveContext).toHaveBeenCalledWith({ orgId: 'new-org' })
    })
})
