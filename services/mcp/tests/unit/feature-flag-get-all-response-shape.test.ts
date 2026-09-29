import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/feature_flags'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const staleFlag = (): Record<string, unknown> => ({
    id: 1,
    key: 'checkout-redesign',
    status: 'STALE',
    last_called_at: '2026-06-01T00:00:00Z',
    active: true,
    created_at: '2026-01-01T00:00:00Z',
    filters: { groups: [{ rollout_percentage: 100, properties: [] }] },
    created_by: { id: 7, email: 'someone@example.com' },
})

describe('feature-flag-get-all response shape', () => {
    it('keeps the staleness evidence on every row and drops filters', async () => {
        const request = vi.fn().mockResolvedValue({ results: [staleFlag()], next: null, previous: null })

        const result = await GENERATED_TOOLS['feature-flag-get-all']!().handler(createMockContext(request), {})

        const row = (result as any).results[0]
        // pickResponseFields drops an unmatched path with no error, so a typo in the yaml include
        // list would silently send agents back to one definition call per flag.
        expect(row).toMatchObject({
            status: 'STALE',
            last_called_at: '2026-06-01T00:00:00Z',
            active: true,
            created_at: '2026-01-01T00:00:00Z',
        })
        expect(row).not.toHaveProperty('filters')
        expect(row).not.toHaveProperty('created_by')
    })
})
