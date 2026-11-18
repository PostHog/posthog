import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { ApiClient } from '@/api/client'
import { DashboardsRunInsightsRetrieveQueryParams } from '@/generated/dashboards/api'
import { createExecTool } from '@/tools/exec'
import { GENERATED_TOOLS } from '@/tools/generated/dashboards'
import type { Context } from '@/tools/types'

describe('dashboard-insights-run', () => {
    const tool = GENERATED_TOOLS['dashboard-insights-run']!()

    it.each([
        [{ dashboard_tile_ids: [101, 102] }, '101,102'],
        [{ tile_ids: [101, 102] }, '101,102'],
        [{ tile_ids: '101,102' }, '101,102'],
        [{ tile_ids: ' 101, 102 ' }, '101,102'],
        [{ dashboard_tile_ids: [101], tile_ids: [102] }, '101'],
        [{}, undefined],
    ])('sends the selected dashboard tiles to the API: %j', async (selector, expected) => {
        const request = vi.fn().mockResolvedValue({ results: [] })
        const context = {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context

        const params = tool.schema.parse({ id: 7, ...selector, output_format: 'json' })
        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                path: '/api/projects/42/dashboards/7/run_insights/',
                query: expect.objectContaining({ tile_ids: expected, output_format: 'json' }),
            })
        )
        expect(request.mock.calls[0]![0].query).not.toHaveProperty('dashboard_tile_ids')
    })

    it.each(['direct', 'exec'])('preserves the tile selection through %s and real HTTP transport', async (mode) => {
        const urls: string[] = []
        const server = createServer((request, response) => {
            urls.push(request.url!)
            response.setHeader('Content-Type', 'application/json')
            response.end(JSON.stringify({ results: [] }))
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
        const context = {
            api: new ApiClient({ apiToken: 'test-token', baseUrl }),
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const exec = createExecTool(
            [
                {
                    ...tool,
                    title: 'Run dashboard insights',
                    description: '',
                    scopes: [],
                    annotations: {
                        readOnlyHint: true,
                        destructiveHint: false,
                        idempotentHint: true,
                        openWorldHint: true,
                    },
                },
            ],
            context,
            '',
            '',
            undefined
        )
        try {
            for (const input of [
                { id: 7, dashboard_tile_ids: [101, 102] },
                { dashboard_id: '7', tile_ids: [101, 102] },
                { dashboardId: 7, tile_ids: '101,102' },
            ]) {
                if (mode === 'exec') {
                    await exec.handler(context, {
                        command: `call --json dashboard-insights-run ${JSON.stringify(input)}`,
                    })
                } else {
                    await tool.handler(context, tool.schema.parse(input))
                }
            }
            const invalid = { id: 7, tile_ids: 'insight-short-id' }
            if (mode === 'exec') {
                await expect(
                    exec.handler(context, {
                        command: `call --json dashboard-insights-run ${JSON.stringify(invalid)}`,
                    })
                ).rejects.toThrow('dashboard_tile_ids')
            } else {
                expect(tool.schema.safeParse(invalid).success).toBe(false)
            }
            expect(urls).toHaveLength(3)
            for (const url of urls) {
                const request = new URL(url, baseUrl)
                expect(request.pathname).toBe('/api/projects/42/dashboards/7/run_insights/')
                expect(request.searchParams.get('tile_ids')).toBe('101,102')
                expect(request.searchParams.has('dashboard_tile_ids')).toBe(false)
            }
        } finally {
            await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
        }
    })

    it('advertises an array while the HTTP API keeps its string contract', () => {
        expect(DashboardsRunInsightsRetrieveQueryParams().shape.tile_ids.safeParse([101, 102]).success).toBe(false)
        expect(DashboardsRunInsightsRetrieveQueryParams().shape.tile_ids.safeParse('101,102').success).toBe(true)
        const schema = z.toJSONSchema(tool.schema, { io: 'input' })
        expect(schema.properties?.dashboard_tile_ids).toMatchObject({ type: 'array', items: { type: 'integer' } })
        expect(schema.properties).not.toHaveProperty('tile_ids')
    })

    it.each(['abc123', '101,abc123', ['abc123'], [0], [-1], [1.5], []].map((ids) => ({ ids })))(
        'rejects an invalid dashboard tile selector: %j',
        ({ ids }) => {
            expect(tool.schema.safeParse({ id: 7, dashboard_tile_ids: ids }).success).toBe(false)
        }
    )
})
