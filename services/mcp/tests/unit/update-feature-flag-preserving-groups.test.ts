import { describe, expect, it, vi } from 'vitest'

import updateFeatureFlagPreservingGroups from '@/tools/featureFlags/updateFeatureFlag'
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

describe('update-feature-flag preserving groups', () => {
    const tool = updateFeatureFlagPreservingGroups()

    it('GETs existing flag, merges group fields into filters, then PATCHes', async () => {
        const existing = {
            id: 9,
            key: 'workspace-rollout',
            filters: {
                aggregation_group_type_index: 0,
                groups: [
                    {
                        properties: [
                            {
                                key: 'plan',
                                type: 'group',
                                group_type_index: 0,
                                operator: 'exact',
                                value: 'enterprise',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
        }
        const patched = { ...existing, filters: { ...existing.filters, groups: [] } }

        const request = vi
            .fn()
            .mockResolvedValueOnce(existing) // GET
            .mockResolvedValueOnce(patched) // PATCH via generated handler

        const result = await tool.handler(createMockContext(request), {
            id: 9,
            filters: {
                groups: [
                    {
                        properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                        rollout_percentage: 50,
                    },
                ],
            },
        })

        expect(request).toHaveBeenCalledTimes(2)
        expect(request.mock.calls[0][0]).toMatchObject({
            method: 'GET',
            path: '/api/projects/42/feature_flags/9/',
        })
        expect(request.mock.calls[1][0]).toMatchObject({
            method: 'PATCH',
            path: '/api/projects/42/feature_flags/9/',
        })
        const patchBody = request.mock.calls[1][0].body as {
            filters: {
                aggregation_group_type_index?: number
                groups: Array<{ properties: Array<{ type?: string; group_type_index?: number; value?: unknown }> }>
            }
        }
        expect(patchBody.filters.aggregation_group_type_index).toBe(0)
        expect(patchBody.filters.groups[0].properties[0].type).toBe('group')
        expect(patchBody.filters.groups[0].properties[0].group_type_index).toBe(0)
        expect(patchBody.filters.groups[0].properties[0].value).toBe('pro')
        expect(result).toMatchObject({ id: 9 })
    })

    it('surfaces GET failures instead of PATCHing unmerged filters', async () => {
        const request = vi.fn().mockRejectedValueOnce(new Error('HTTP 429: rate limited'))

        await expect(
            tool.handler(createMockContext(request), {
                id: 9,
                filters: {
                    groups: [
                        {
                            properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                            rollout_percentage: 50,
                        },
                    ],
                },
            })
        ).rejects.toThrow(/429|rate limited/i)

        // Only GET attempted — no corrupt PATCH
        expect(request).toHaveBeenCalledTimes(1)
        expect(request.mock.calls[0][0].method).toBe('GET')
    })

    it('forwards updates without filters without an extra GET', async () => {
        const request = vi.fn().mockResolvedValue({ id: 9, key: 'x', active: false })

        await tool.handler(createMockContext(request), { id: 9, active: false })

        // Generated handler does a single PATCH; no merge GET
        expect(request).toHaveBeenCalledTimes(1)
        expect(request.mock.calls[0][0].method).toBe('PATCH')
        expect(request.mock.calls[0][0].body).toMatchObject({ active: false })
    })
})
