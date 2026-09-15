import { describe, expect, it, vi } from 'vitest'

import setActiveOrganizationTool from '@/tools/organizations/setActive'
import type { Context } from '@/tools/types'

function createMockContext(overrides: { organizationGet: ReturnType<typeof vi.fn> }): {
    context: Context
    cache: Map<string, unknown>
} {
    const cache = new Map<string, unknown>()
    const context = {
        api: {
            publicBaseUrl: 'https://us.posthog.com',
            organizations: () => ({ get: overrides.organizationGet }),
        },
        cache: {
            get: async (key: string) => cache.get(key),
            set: async (key: string, value: unknown) => {
                cache.set(key, value)
            },
        },
        stateManager: {
            getOrFetchIntegrationKinds: vi.fn().mockResolvedValue(undefined),
        },
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
    return { context, cache }
}

describe('switch-organization', () => {
    const tool = setActiveOrganizationTool()

    it('does not commit the session and preserves the error cause when the organization is unreachable', async () => {
        const apiError = new Error('404')
        const organizationGet = vi.fn().mockResolvedValue({ success: false, error: apiError })
        const { context, cache } = createMockContext({ organizationGet })

        let caught: (Error & { cause?: unknown }) | undefined
        try {
            await tool.handler(context, { orgId: 'org-999' })
        } catch (e) {
            caught = e as Error & { cause?: unknown }
        }

        expect(caught?.message).toMatch(/Could not switch to organization org-999.*organizations-get/s)
        expect(caught?.cause).toBe(apiError)
        // A failed switch must not strand the session on an unreachable organization.
        expect(cache.get('orgId')).toBeUndefined()
    })

    it('commits the session and caches the organization when the fetch succeeds', async () => {
        const organizationGet = vi.fn().mockResolvedValue({
            success: true,
            data: { id: 'org-123', name: 'My org' },
        })
        const { context, cache } = createMockContext({ organizationGet })

        const result = await tool.handler(context, { orgId: 'org-123' })

        expect(result.content[0]!.text).toContain('Switched to organization org-123')
        expect(cache.get('orgId')).toBe('org-123')
        expect(cache.get('cachedOrg:org-123')).toEqual({ id: 'org-123', name: 'My org' })
    })
})
