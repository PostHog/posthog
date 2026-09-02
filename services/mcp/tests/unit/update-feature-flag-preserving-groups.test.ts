import { describe, expect, it, vi } from 'vitest'

import updateFeatureFlagPreservingGroups from '@/tools/featureFlags/updateFeatureFlag'
import type { Context } from '@/tools/types'

type ApiRequestArgs = { method: string; path: string; body?: unknown }

function requestArgs(requestMock: ReturnType<typeof vi.fn>, callIndex: number): ApiRequestArgs {
    const call = requestMock.mock.calls[callIndex]
    if (!call) {
        throw new Error(`Expected an api.request call at index ${callIndex}`)
    }
    return call[0] as ApiRequestArgs
}

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
            name: 'Renamed',
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
        expect(requestArgs(request, 0)).toMatchObject({
            method: 'GET',
            path: '/api/projects/42/feature_flags/9/',
        })
        expect(requestArgs(request, 1)).toMatchObject({
            method: 'PATCH',
            path: '/api/projects/42/feature_flags/9/',
        })
        const patchBody = requestArgs(request, 1).body as {
            name?: string
            filters: {
                aggregation_group_type_index?: number
                groups: Array<{ properties: Array<{ type?: string; group_type_index?: number; value?: unknown }> }>
            }
        }
        // Non-filters fields must still be forwarded alongside the merged filters.
        expect(patchBody).toMatchObject({ name: 'Renamed' })
        expect(patchBody.filters.aggregation_group_type_index).toBe(0)
        expect(patchBody.filters.groups[0]?.properties[0]?.type).toBe('group')
        expect(patchBody.filters.groups[0]?.properties[0]?.group_type_index).toBe(0)
        expect(patchBody.filters.groups[0]?.properties[0]?.value).toBe('pro')
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
        expect(requestArgs(request, 0).method).toBe('GET')
    })

    it('forwards updates without filters without an extra GET', async () => {
        const request = vi.fn().mockResolvedValue({ id: 9, key: 'x', active: false })

        await tool.handler(createMockContext(request), { id: 9, active: false })

        // Generated handler does a single PATCH; no merge GET
        expect(request).toHaveBeenCalledTimes(1)
        expect(requestArgs(request, 0).method).toBe('PATCH')
        expect(requestArgs(request, 0).body).toMatchObject({ active: false })
    })
})
