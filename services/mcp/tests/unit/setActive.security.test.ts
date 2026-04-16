import { describe, expect, it, vi } from 'vitest'

import { setActiveHandler as setActiveOrganizationHandler } from '@/tools/organizations/setActive'
import type { Context } from '@/tools/types'

const createMockContext = (): { context: Context; cacheSet: ReturnType<typeof vi.fn> } => {
    const cacheSet = vi.fn(async () => undefined)
    const context = {
        api: {} as any,
        cache: {
            get: vi.fn(),
            set: cacheSet,
            delete: vi.fn(),
            clear: vi.fn(),
        } as any,
        env: {} as any,
        stateManager: {
            invalidateAiConsent: vi.fn(async () => undefined),
        } as any,
        sessionManager: {} as any,
    } as Context
    return { context, cacheSet }
}

describe('switch-organization security', () => {
    it.each([
        ['path traversal', 'org-uuid/../admin'],
        ['CRLF injection', '01958a09-3ec3-7000-3a82-d5d2729fdfe1\r\nX-Evil: 1'],
        ['query string injection', '01958a09-3ec3-7000-3a82-d5d2729fdfe1?delete=true'],
        ['shell metacharacters', '01958a09-3ec3-7000-3a82-d5d2729fdfe1; rm -rf /'],
        ['empty string', ''],
        ['bare path component', '../'],
        ['javascript scheme', 'javascript:alert(1)'],
    ])('refuses to cache %s and never poisons the URL-bound cache', async (_name, hostileOrgId) => {
        const { context, cacheSet } = createMockContext()

        const result = await setActiveOrganizationHandler(context, { orgId: hostileOrgId })

        // The cache write that would otherwise put a hostile value into the
        // URL path of every subsequent request must NOT have happened.
        expect(cacheSet).not.toHaveBeenCalled()
        // And the user gets a clear rejection.
        expect(result.content[0]!.text).toMatch(/Invalid organization ID format/)
    })

    it('accepts a valid UUID', async () => {
        const { context, cacheSet } = createMockContext()

        const result = await setActiveOrganizationHandler(context, {
            orgId: '01958a09-3ec3-7000-3a82-d5d2729fdfe1',
        })

        expect(cacheSet).toHaveBeenCalledWith('orgId', '01958a09-3ec3-7000-3a82-d5d2729fdfe1')
        expect(result.content[0]!.text).toMatch(/Switched to organization/)
    })

    it('accepts the @current literal', async () => {
        const { context, cacheSet } = createMockContext()

        const result = await setActiveOrganizationHandler(context, { orgId: '@current' })

        expect(cacheSet).toHaveBeenCalledWith('orgId', '@current')
        expect(result.content[0]!.text).toMatch(/Switched to organization @current/)
    })
})
