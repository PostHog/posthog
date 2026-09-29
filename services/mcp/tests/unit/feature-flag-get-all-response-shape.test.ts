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
    name: 'Checkout redesign',
    updated_at: '2026-08-25T00:00:00Z',
    status: 'STALE',
    tags: ['checkout'],
    last_called_at: '2026-06-01T00:00:00Z',
    active: true,
    archived: false,
    created_at: '2026-01-01T00:00:00Z',
    // The second group omits `rollout_percentage`, which the backend treats as 100%.
    filters: {
        groups: [
            { rollout_percentage: 50, properties: [{ key: 'email', value: 'a@example.com' }] },
            { properties: [] },
        ],
        multivariate: { variants: [{ key: 'test', rollout_percentage: 100 }] },
        payloads: { test: '{"a":1}' },
    },
    created_by: { id: 7, email: 'someone@example.com' },
})

describe('feature-flag-get-all response shape', () => {
    it('keeps the staleness evidence fields on every row and drops the rest of filters', async () => {
        const request = vi.fn().mockResolvedValue({ results: [staleFlag()], next: null, previous: null })

        const result = await GENERATED_TOOLS['feature-flag-get-all']!().handler(createMockContext(request), {})

        const row = (result as any).results[0]
        // Without these an agent has to call feature-flag-get-definition once per flag.
        expect(row.last_called_at).toBe('2026-06-01T00:00:00Z')
        expect(row.active).toBe(true)
        expect(row.archived).toBe(false)
        expect(row.created_at).toBe('2026-01-01T00:00:00Z')
        expect(row.status).toBe('STALE')

        // A group with no rollout_percentage projects as `{}`, so the row cannot distinguish it
        // from one the flag never set. The tool description warns agents about exactly this.
        expect(row.filters.groups).toEqual([{ rollout_percentage: 50 }, {}])

        // Targeting and variant payloads stay out to keep the row small, which is also why the
        // description tells agents never to send this filters object to update-feature-flag.
        expect(row.filters).not.toHaveProperty('multivariate')
        expect(row.filters).not.toHaveProperty('payloads')
        expect(row.filters.groups[0]).not.toHaveProperty('properties')
        expect(row).not.toHaveProperty('created_by')
    })
})
