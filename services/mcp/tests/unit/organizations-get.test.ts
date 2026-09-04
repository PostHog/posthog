import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
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

    it('returns accessible organizations filtered to the safe id/name/slug/membership fields', async () => {
        // The `/api/organizations/` rows carry the full serializer, so the raw
        // data includes billing/security fields the tool must not expose.
        const orgs = [
            {
                id: 'org-a',
                name: 'Org A',
                slug: 'org-a',
                membership_level: 8,
                customer_id: 'cus_secret',
                available_product_features: [{ key: 'sso' }],
            },
            {
                id: 'org-b',
                name: 'Org B',
                slug: 'org-b',
                membership_level: 1,
                enforce_2fa: true,
                is_hipaa: true,
            },
        ]
        const list = vi.fn().mockResolvedValue({ success: true, data: orgs })

        const result = await tool.handler(createMockContext(list), {})

        expect(result).toEqual([
            { id: 'org-a', name: 'Org A', slug: 'org-a', membership_level: 8 },
            { id: 'org-b', name: 'Org B', slug: 'org-b', membership_level: 1 },
        ])
        for (const org of result) {
            expect(org).not.toHaveProperty('customer_id')
            expect(org).not.toHaveProperty('available_product_features')
            expect(org).not.toHaveProperty('enforce_2fa')
            expect(org).not.toHaveProperty('is_hipaa')
        }
    })

    it('throws a descriptive error and preserves the API error cause when the list request fails', async () => {
        const apiError = new Error('boom')
        const list = vi.fn().mockResolvedValue({ success: false, error: apiError })

        let caught: (Error & { cause?: unknown }) | undefined
        try {
            await tool.handler(createMockContext(list), {})
        } catch (e) {
            caught = e as Error & { cause?: unknown }
        }

        expect(caught?.message).toMatch(/Failed to get organizations: boom/)
        // Preserving the cause lets handleToolError classify the recoverable 4xx
        // and keep it out of exception tracking.
        expect(caught?.cause).toBe(apiError)
    })

    it('turns a 404 into a terminal, non-retryable message while staying a 404', async () => {
        const apiError = new PostHogApiError({
            status: 404,
            statusText: 'Not Found',
            body: '',
            url: 'https://us.posthog.com/api/organizations/',
            method: 'GET',
        })
        const list = vi.fn().mockResolvedValue({ success: false, error: apiError })

        let caught: PostHogApiError | undefined
        try {
            await tool.handler(createMockContext(list), {})
        } catch (e) {
            caught = e as PostHogApiError
        }

        // Still a 404 so handleToolError classifies it as a recoverable 4xx and the
        // analytics summary (rebuilt from status + method + path) is unchanged.
        expect(caught).toBeInstanceOf(PostHogApiError)
        expect(caught?.status).toBe(404)
        // The agent-facing message names the cause and tells it not to retry, which
        // is what the bare `HTTP 404` status failed to do.
        expect(caught?.message).toMatch(/not a transient error/)
        expect(caught?.message).toMatch(/region mismatch/)
        expect(caught?.message).toMatch(/Do not retry/)
    })
})
