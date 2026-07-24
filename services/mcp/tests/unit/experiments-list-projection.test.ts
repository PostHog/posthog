/**
 * Tests for the generated `experiment-list` response projection.
 *
 * `experiment-list` is a summary/list endpoint: rows should carry enough of the
 * linked flag to identify it and show the variant split, but NOT its full
 * configuration. Filter groups can hold targeting values (including PII such as
 * email conditions), which belong only on the `experiment-get` detail payload.
 * These tests pin that boundary so re-adding the full `feature_flag` object to
 * the include list — or dropping the projection — fails loudly.
 */
import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PROJECT_ID = '2'

function getTool(): ToolBase<ZodObjectAny> {
    return (GENERATED_TOOLS['experiment-list'] as () => ToolBase<ZodObjectAny>)()
}

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: () => `https://us.posthog.com/project/${PROJECT_ID}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue(PROJECT_ID) } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const EMAIL = 'targeted-user@example.com'

const listResponseWithTargeting = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 379357,
            name: 'Running experiment',
            description: 'desc',
            feature_flag_key: 'my-flag',
            start_date: '2026-01-01T00:00:00Z',
            end_date: null,
            archived: false,
            type: 'product',
            status: 'running',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-02T00:00:00Z',
            feature_flag: {
                id: 42,
                team_id: 2,
                key: 'my-flag',
                name: 'My flag',
                active: true,
                deleted: false,
                filters: {
                    groups: [
                        {
                            rollout_percentage: 100,
                            properties: [{ key: 'email', type: 'person', value: [EMAIL], operator: 'exact' }],
                        },
                    ],
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                },
            },
        },
    ],
}

describe('experiment-list response projection', () => {
    it('strips filter groups (and their targeting values) from the linked flag on list rows', async () => {
        const requestMock = vi.fn().mockResolvedValue(listResponseWithTargeting)
        const result: any = await getTool().handler(createMockContext(requestMock), { project_id: PROJECT_ID } as any)

        const flag = result.results[0].feature_flag
        // Identity + variant split survive — that's what a list row needs.
        expect(flag).toMatchObject({ id: 42, key: 'my-flag', name: 'My flag', active: true })
        expect(flag.filters.multivariate.variants.map((v: any) => v.key)).toEqual(['control', 'test'])

        // Filter groups (and any targeting values inside) never reach the list row.
        expect(flag.filters.groups).toBeUndefined()
        expect(JSON.stringify(result)).not.toContain(EMAIL)
    })
})
