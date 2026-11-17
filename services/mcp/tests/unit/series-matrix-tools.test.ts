import { describe, expect, it, vi } from 'vitest'

import { buildToolResultPayload } from '@/lib/build-tool-result'
import { GENERATED_TOOLS as METRICS_TOOLS } from '@/tools/generated/metrics'
import { GENERATED_TOOLS as QUERY_WRAPPER_TOOLS } from '@/tools/generated/query-wrappers'
import type { Context } from '@/tools/types'

function contextReturning(response: unknown): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(response),
            query: vi.fn().mockReturnValue({ runQuery: vi.fn().mockResolvedValue(response) }),
            getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getCachedOrFetchProject: vi.fn().mockResolvedValue({}),
        },
    } as unknown as Context
}

async function textOf(
    tools: Record<string, () => any>,
    name: string,
    params: unknown,
    response: unknown
): Promise<any> {
    const tool = tools[name]!()
    const handlerResult = await tool.handler(contextReturning(response), params)
    const payload = buildToolResultPayload({ handlerResult, toolMeta: tool._meta, toolName: tool.name, params })
    return JSON.parse((payload.content[0] as { text: string }).text)
}

const TRENDS_PARAMS = { series: [{ kind: 'EventsNode', event: '$pageview' }] }

describe('chart series tools', () => {
    it.each([
        {
            name: 'a grouped range query',
            series: {
                labels: { service_name: 'api' },
                points: [
                    { time: '2026-01-01T00:00:00Z', value: 2 },
                    { time: '2026-01-01T01:00:00Z', value: null },
                ],
                metric_name: 'http_requests_total',
                clause: null,
            },
            expected: {
                metric: { __name__: 'http_requests_total', service_name: 'api' },
                values: [
                    ['2026-01-01T00:00:00Z', 2],
                    ['2026-01-01T01:00:00Z', null],
                ],
            },
        },
        {
            name: 'a formula series with no labels',
            series: {
                labels: {},
                points: [{ time: '2026-01-01T00:00:00Z', value: 0.5 }],
                metric_name: null,
                clause: 'a',
            },
            expected: { metric: { __name__: 'a' }, values: [['2026-01-01T00:00:00Z', 0.5]] },
        },
    ])('query-metrics-easel returns $name as labels and time-value pairs', async ({ series, expected }) => {
        const text = await textOf(
            METRICS_TOOLS,
            'query-metrics-easel',
            { query: { promql: 'up' } },
            { results: [series], url_params: 'query=up' }
        )

        expect(text.results).toEqual([expected])
    })

    it('query-metrics-easel keeps an instant result, which has no points', async () => {
        const instant = { labels: { service_name: 'api' }, value: 3, time: '2026-01-01T00:00:00Z' }

        const tool = METRICS_TOOLS['query-metrics-easel']!()
        const result = (await tool.handler(contextReturning({ results: [instant], url_params: '' }), {
            query: { promql: 'up', instant: true },
        } as never)) as { results: unknown[] }

        expect(result.results).toEqual([instant])
    })

    it.each([
        {
            name: 'a plain series under its event name',
            series: {
                label: '$pageview',
                action: { name: '$pageview' },
                days: ['2026-01-01', '2026-01-02'],
                data: [3, 0],
            },
            expected: {
                metric: { series: '$pageview' },
                values: [
                    ['2026-01-01', 3],
                    ['2026-01-02', 0],
                ],
            },
        },
        {
            name: 'a breakdown and comparison series with all three labels',
            series: {
                label: 'Chrome',
                action: { name: '$pageview', custom_name: 'Views' },
                breakdown_value: 'Chrome',
                compare_label: 'previous',
                days: ['2026-01-01'],
                data: [7],
            },
            expected: {
                metric: { series: 'Views', breakdown: 'Chrome', compare: 'previous' },
                values: [['2026-01-01', 7]],
            },
        },
    ])('query-trends-easel returns $name', async ({ series, expected }) => {
        const text = await textOf(QUERY_WRAPPER_TOOLS, 'query-trends-easel', TRENDS_PARAMS, { results: [series] })

        expect(text.results).toEqual([expected])
    })

    it('query-trends-easel keeps a total-value result, which has no dates', async () => {
        const total = { label: '$pageview', aggregated_value: 12, data: [] }

        const text = await textOf(QUERY_WRAPPER_TOOLS, 'query-trends-easel', TRENDS_PARAMS, { results: [total] })

        expect(text.results).toEqual([total])
    })
})
