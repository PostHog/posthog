import { describe, expect, it, vi } from 'vitest'

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
        api: { request, getProjectBaseUrl: () => 'https://app.example.com/project/7' },
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

    it('experiment-update merges the variant inputs into the stored parameters without flag config', async () => {
        const { context, request } = contextWith({ GET: { id: 1, parameters: STORED_PARAMETERS }, PATCH: { id: 1 } })

        await run('experiment-update', context, { id: '1', name: 'Renamed', variant_notes: { test: 'new copy' } })

        expect(sentBody(request, 'PATCH')).toEqual({
            name: 'Renamed',
            parameters: {
                prompt_metadata: STORED_PARAMETERS.prompt_metadata,
                variant_notes: { control: 'baseline', test: 'new copy' },
                variant_screenshot_media_ids: { control: ['media-1'] },
            },
        })
    })

    it('experiment-update does not read or send parameters without variant inputs', async () => {
        const { context, request } = contextWith({ PATCH: { id: 1 } })

        await run('experiment-update', context, { id: 1, name: 'Renamed' })

        expect(request.mock.calls.map(([options]) => options.method)).toEqual(['PATCH'])
        expect(sentBody(request, 'PATCH')).toEqual({ name: 'Renamed' })
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
                            variant_screenshot_media_ids: { control: ['media-1'], test: [] },
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
            { id: 1, parameters: undefined, variants_with_notes: ['control'], variants_with_screenshots: ['control'] },
            { id: 2, parameters: undefined, variants_with_notes: [], variants_with_screenshots: [] },
        ])
    })
})
