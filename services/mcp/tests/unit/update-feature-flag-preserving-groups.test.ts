import { describe, expect, it, vi } from 'vitest'

import { PostHogValidationError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/feature_flags'
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
    const tool = GENERATED_TOOLS['update-feature-flag']!()

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

        // The merge reads key presence, so a codegen default on an aggregation key would turn it
        // into a no-op. Params built by hand never catch that, so parse through the tool's own schema.
        const params = tool.schema.parse({
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

        const result = await tool.handler(createMockContext(request), params)

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

        expect(request).toHaveBeenCalledTimes(1)
        expect(requestArgs(request, 0).method).toBe('GET')
    })

    it('forwards updates without filters without an extra GET', async () => {
        const request = vi.fn().mockResolvedValue({ id: 9, key: 'x', active: false })

        await tool.handler(createMockContext(request), { id: 9, active: false })

        expect(request).toHaveBeenCalledTimes(1)
        expect(requestArgs(request, 0).method).toBe('PATCH')
        expect(requestArgs(request, 0).body).toMatchObject({ active: false })
    })

    describe('untyped property error', () => {
        const existing = {
            id: 9,
            key: 'pricing-banner',
            filters: {
                groups: [
                    {
                        properties: [{ key: 'country', type: 'person', operator: 'exact', value: 'US' }],
                        rollout_percentage: 100,
                    },
                ],
            },
        }

        // groups[0].properties[1] holds `email`, so a hook that swaps the group and property indices names the wrong key.
        const params = tool.schema.parse({
            id: 9,
            filters: {
                groups: [
                    {
                        properties: [
                            { key: 'country', type: 'person', operator: 'exact', value: 'US' },
                            { key: 'email', type: 'person', operator: 'exact', value: 'someone@example.com' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                        rollout_percentage: 50,
                    },
                ],
            },
        })

        function rejectPatchWith(
            detail: string,
            code: string
        ): { request: ReturnType<typeof vi.fn>; error: PostHogValidationError } {
            const error = new PostHogValidationError({
                detail,
                attr: 'filters',
                code,
                extra: undefined,
                url: 'https://us.posthog.com/api/projects/42/feature_flags/9/',
                method: 'PATCH',
            })
            const request = vi.fn().mockResolvedValueOnce(existing).mockRejectedValueOnce(error)
            return { request, error }
        }

        it.each([
            {
                shape: 'serde guard',
                detail: 'groups[1].properties[0].type: invalid property type',
                code: 'invalid',
            },
            {
                shape: 'structural',
                detail: 'groups[1].properties[0].type: This field is required.',
                code: 'structural.groups[].properties[].type.required',
            },
        ])('names the rejected property and its fix for the $shape rejection', async ({ detail, code }) => {
            const { request } = rejectPatchWith(detail, code)

            const rejection: unknown = await tool.handler(createMockContext(request), params).catch((e: unknown) => e)

            expect(rejection).toBeInstanceOf(PostHogValidationError)
            expect(rejection).toMatchObject({ attr: 'filters', code, method: 'PATCH' })
            const { message } = rejection as PostHogValidationError
            expect(message).toContain(detail)
            expect(message).toContain('filters.groups[1].properties[0]')
            expect(message).toContain('"plan"')
            expect(message).toContain("Don't guess `person`")
            expect(message).not.toContain('"email"')
        })

        it.each([
            {
                scenario: 'a different field under filters',
                detail: 'groups[0].properties[0].operator: "foo" is not a valid choice.',
                code: 'structural.groups[].properties[].operator.invalid_choice',
            },
            {
                scenario: 'a type path the sent filters do not contain',
                detail: 'groups[5].properties[0].type: invalid property type',
                code: 'invalid',
            },
        ])('rethrows the API error unchanged for $scenario', async ({ detail, code }) => {
            const { request, error } = rejectPatchWith(detail, code)

            await expect(tool.handler(createMockContext(request), params)).rejects.toBe(error)
        })
    })
})
