import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/dashboards'
import type { Context } from '@/tools/types'

describe('dashboard-insights-run', () => {
    const tool = GENERATED_TOOLS['dashboard-insights-run']!()

    it.each([
        [[101, 102], '101,102'],
        [undefined, undefined],
    ])('sends the selected dashboard tiles to the API: %j', async (ids, expected) => {
        const request = vi.fn().mockResolvedValue({ results: [] })
        const context = {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context

        const params = tool.schema.parse({ id: 7, dashboard_tile_ids: ids, output_format: 'json' })
        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                path: '/api/projects/42/dashboards/7/run_insights/',
                query: expect.objectContaining({ tile_ids: expected, output_format: 'json' }),
            })
        )
        expect(request.mock.calls[0]![0].query).not.toHaveProperty('dashboard_tile_ids')
    })

    it.each(['abc123', '101,102', ['abc123'], [0], [-1], [1.5], []].map((ids) => ({ ids })))(
        'rejects an invalid dashboard tile selector: %j',
        ({ ids }) => {
            expect(tool.schema.safeParse({ id: 7, dashboard_tile_ids: ids }).success).toBe(false)
        }
    )
})
