import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const STORED_PARAMETERS = {
    // Reads project the flag config into `parameters`; writes must not send it back.
    feature_flag_variants: [{ key: 'control', rollout_percentage: 50 }],
    rollout_percentage: 100,
    prompt_metadata: { name: 'greeting', templates: [], versions: [1, 2] },
    variant_notes: { control: 'baseline', test: 'old copy' },
    variant_screenshot_media_ids: { control: ['media-1'] },
}

function contextWith(responses: Record<string, unknown>): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn(async ({ method }: { method: string }) => responses[method])
    const context = {
        stateManager: { getProjectId: async () => '7' },
        api: {
            request,
            publicBaseUrl: 'https://app.example.com',
            getProjectBaseUrl: () => 'https://app.example.com/project/7',
        },
    } as unknown as Context
    return { context, request }
}

async function run(toolName: string, context: Context, args: Record<string, unknown>): Promise<unknown> {
    const tool = (GENERATED_TOOLS[toolName] as () => ToolBase<ZodObjectAny>)()
    return tool.handler(context, tool.schema.parse(args))
}

function sentBody(request: ReturnType<typeof vi.fn>, method: string): Record<string, unknown> | undefined {
    return request.mock.calls.map(([options]) => options).find((options) => options.method === method)?.body
}

describe('experiment variant notes and screenshots', () => {
    it('experiment-create sends the variant inputs inside parameters', async () => {
        const { context, request } = contextWith({ POST: { id: 1 } })

        await run('experiment-create', context, {
            name: 'Checkout',
            feature_flag_key: 'checkout',
            variant_notes: { test: 'one-page checkout' },
            variant_screenshot_media_ids: { test: ['media-2'] },
        })

        const body = sentBody(request, 'POST')
        expect(body).not.toHaveProperty('variant_notes')
        expect(body?.parameters).toEqual({
            variant_notes: { test: 'one-page checkout' },
            variant_screenshot_media_ids: { test: ['media-2'] },
        })
    })

    it.each([4, null])('experiment-update preserves parameters and the read version %s', async (version) => {
        const { context, request } = contextWith({
            GET: { id: 1, version, parameters: STORED_PARAMETERS },
            PATCH: { id: 1 },
        })

        await run('experiment-update', context, { id: '1', name: 'Renamed', variant_notes: { test: 'new copy' } })

        expect(sentBody(request, 'PATCH')).toEqual({
            name: 'Renamed',
            version: version ?? 0,
            parameters: {
                prompt_metadata: STORED_PARAMETERS.prompt_metadata,
                variant_notes: { control: 'baseline', test: 'new copy' },
                variant_screenshot_media_ids: { control: ['media-1'] },
            },
        })
    })

    it('refuses an interleaved edit and preserves both changes on a fresh retry', async () => {
        let stored = { id: 1, version: 4, parameters: STORED_PARAMETERS }
        const { context, request } = contextWith({})
        request.mockImplementation(async ({ method, body }: { method: string; body?: Record<string, unknown> }) => {
            if (method === 'GET') {
                return { ...stored }
            }
            if (body?.version !== undefined && body.version !== stored.version) {
                throw new PostHogApiError({
                    status: 409,
                    statusText: 'Conflict',
                    body: 'This experiment changed since you loaded it. Review the latest changes and try again.',
                    url: 'https://app.example.com/api/projects/7/experiments/1/',
                    method,
                })
            }
            stored = {
                ...stored,
                version: stored.version + 1,
                parameters: body?.parameters as typeof STORED_PARAMETERS,
            }
            return stored
        })

        const results = await Promise.allSettled([
            run('experiment-update', context, { id: 1, variant_notes: { control: 'first edit' } }),
            run('experiment-update', context, { id: 1, variant_notes: { test: 'second edit' } }),
        ])

        expect(results[0]?.status).toBe('fulfilled')
        expect(results[1]).toMatchObject({ status: 'rejected', reason: { status: 409 } })
        expect(stored.parameters.variant_notes).toEqual({ control: 'first edit', test: 'old copy' })

        await run('experiment-update', context, { id: 1, variant_notes: { test: 'second edit' } })

        expect(stored.parameters.variant_notes).toEqual({ control: 'first edit', test: 'second edit' })
    })

    it('experiment-update does not read or send parameters without variant inputs', async () => {
        const { context, request } = contextWith({ PATCH: { id: 1 } })

        await run('experiment-update', context, { id: 1, name: 'Renamed' })

        expect(request.mock.calls.map(([options]) => options.method)).toEqual(['PATCH'])
        expect(sentBody(request, 'PATCH')).toEqual({ name: 'Renamed' })
    })

    it('experiment-get maps each variant screenshot media ID to its viewable URL', async () => {
        const { context } = contextWith({
            GET: {
                id: 1,
                parameters: { variant_screenshot_media_ids: { control: ['media-1', 'media-2'], test: 'media-3' } },
            },
        })

        const result = (await run('experiment-get', context, { id: 1 })) as Record<string, unknown>

        expect(result.variant_screenshot_urls).toEqual({
            control: [
                'https://app.example.com/uploaded_media/media-1',
                'https://app.example.com/uploaded_media/media-2',
            ],
            test: ['https://app.example.com/uploaded_media/media-3'],
        })
    })

    it('experiment-list reports which variants have notes or screenshots', async () => {
        const { context } = contextWith({
            GET: {
                count: 2,
                results: [
                    {
                        id: 1,
                        name: 'Checkout',
                        parameters: {
                            ...STORED_PARAMETERS,
                            variant_notes: { control: 'baseline', test: '' },
                            variant_screenshot_media_ids: {
                                control: ['media-1'],
                                test: [],
                                legacy: 'media-3',
                                empty: '',
                                blank: [''],
                            },
                        },
                    },
                    { id: 2, name: 'Pricing', parameters: null },
                ],
            },
        })

        const result = (await run('experiment-list', context, {})) as { results: Record<string, unknown>[] }

        expect(
            result.results.map(({ id, parameters, variants_with_notes, variants_with_screenshots }) => ({
                id,
                parameters,
                variants_with_notes,
                variants_with_screenshots,
            }))
        ).toEqual([
            {
                id: 1,
                parameters: undefined,
                variants_with_notes: ['control'],
                variants_with_screenshots: ['control', 'legacy'],
            },
            { id: 2, parameters: undefined, variants_with_notes: [], variants_with_screenshots: [] },
        ])
    })
})
