import { describe, expect, it, vi } from 'vitest'

import getOrganizationsTool from '@/tools/organizations/getOrganizations'
import type { Context } from '@/tools/types'

function createMockContext(list: ReturnType<typeof vi.fn>): Context {
    return {
        api: { organizations: () => ({ list }) },
        cache: {},
        stateManager: {},
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

describe('organizations-get', () => {
    const tool = getOrganizationsTool()

    it('is registered under the expected tool name', () => {
        expect(tool.name).toBe('organizations-get')
    })

    it('returns every organization the user can access, including ones outside the active org', async () => {
        const orgs = [
            { id: 'org-a', name: 'Org A' },
            { id: 'org-b', name: 'Org B' },
        ]
        const list = vi.fn().mockResolvedValue({ success: true, data: orgs })

        const result = await tool.handler(createMockContext(list), {})

        expect(result).toEqual(orgs)
    })

    it('throws a descriptive error when the list request fails', async () => {
        const list = vi.fn().mockResolvedValue({ success: false, error: new Error('boom') })

        await expect(tool.handler(createMockContext(list), {})).rejects.toThrow(/Failed to get organizations: boom/)
    })
})
