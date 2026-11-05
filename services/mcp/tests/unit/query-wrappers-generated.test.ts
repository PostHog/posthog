import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'
import type { Context } from '@/tools/types'

const behavioralFilter = {
    type: 'behavioral',
    value: 'performed_event',
    key: 'user invited',
    event_type: 'events',
    negation: true,
    time_value: 30,
    time_interval: 'day',
}

const insightQueries = [
    ['query-trends', { series: [{ kind: 'EventsNode', event: '$pageview' }] }],
    [
        'query-funnel',
        {
            series: [
                { kind: 'EventsNode', event: '$pageview' },
                { kind: 'EventsNode', event: 'user signed up' },
            ],
        },
    ],
    [
        'query-retention',
        {
            retentionFilter: {
                targetEntity: { type: 'events', id: '$pageview' },
                returningEntity: { type: 'events', id: '$pageview' },
            },
        },
    ],
    ['query-stickiness', { series: [{ kind: 'EventsNode', event: '$pageview' }] }],
    ['query-paths', { pathsFilter: {} }],
    ['query-lifecycle', { series: [{ kind: 'EventsNode', event: '$pageview' }] }],
] as const

describe('generated query wrappers', () => {
    it.each(insightQueries)('accepts behavioral filters for %s', (toolName, query) => {
        const tool = GENERATED_TOOLS[toolName]!()

        expect(tool.schema.safeParse({ ...query, properties: [behavioralFilter] }).success).toBe(true)
    })

    it('runs a saved funnel with total math once and keeps raw entrant counts', async () => {
        const results = [
            {
                days: ['2026-10-05'],
                data: [42],
                reached_from_step_count: [100],
                reached_to_step_count: [42],
            },
        ]
        const runQuery = vi.fn().mockResolvedValue({ results, formatted_results: '42% conversion' })
        const context = {
            api: {
                query: vi.fn().mockReturnValue({ runQuery }),
                getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
            },
            stateManager: {
                getProjectId: vi.fn().mockResolvedValue('1'),
                getCachedOrFetchProject: vi.fn().mockResolvedValue({ test_account_filters_default_checked: false }),
            },
        } as unknown as Context
        const tool = GENERATED_TOOLS['query-funnel']!()
        const params = tool.schema.parse({
            kind: 'FunnelsQuery',
            series: [
                { kind: 'EventsNode', event: 'sign up', math: 'total' },
                { kind: 'EventsNode', event: 'purchase', math: 'total' },
            ],
            dateRange: { date_from: '-8w' },
            interval: 'week',
            funnelsFilter: { funnelVizType: 'trends' },
            output_format: 'json',
        })
        const result = await tool.handler(context, params)

        expect(runQuery).toHaveBeenCalledTimes(1)
        expect(runQuery).toHaveBeenCalledWith({
            query: expect.objectContaining({
                kind: 'FunnelsQuery',
                series: [
                    expect.objectContaining({ event: 'sign up', math: 'total' }),
                    expect.objectContaining({ event: 'purchase', math: 'total' }),
                ],
            }),
        })
        expect(result).toMatchObject({ results })
    })

    it('rejects unsupported behavioral count operators', () => {
        const tool = GENERATED_TOOLS['query-trends']!()

        expect(
            tool.schema.safeParse({
                ...insightQueries[0][1],
                properties: [
                    {
                        ...behavioralFilter,
                        value: 'performed_event_multiple',
                        operator: 'is_not',
                        operator_value: 2,
                    },
                ],
            }).success
        ).toBe(false)
    })

    it('does not advertise group aggregation for stickiness queries', () => {
        const querySchema = z.toJSONSchema(GENERATED_TOOLS['query-stickiness']!().schema, {
            io: 'input',
            reused: 'inline',
        })
        const actorsSchema = z.toJSONSchema(GENERATED_TOOLS['query-stickiness-actors']!().schema, {
            io: 'input',
            reused: 'inline',
        })

        expect(querySchema.properties).not.toHaveProperty('aggregation_group_type_index')
        expect(actorsSchema.properties?.source).not.toHaveProperty('properties.aggregation_group_type_index')
    })

    it('describes every trends display type it accepts', () => {
        const schema = z.toJSONSchema(GENERATED_TOOLS['query-trends']!().schema, { io: 'input', reused: 'inline' })
        const display = (schema.properties!.trendsFilter as any).properties.display
        // The MCP formatter and chart app ignore calendar_heatmap_data, so agents should not pick it yet.
        const undescribed = ['CalendarHeatmap']

        for (const value of display.enum.filter((v: string) => !undescribed.includes(v))) {
            expect(display.description).toContain(`\`${value}\` - `)
        }
        for (const unsupported of ['Auto', 'ScatterPlot', 'TwoDimensionalHeatmap']) {
            expect(display.enum).not.toContain(unsupported)
        }
    })

    it.each([
        ['zero interval count', 0, false],
        ['one interval', 1, true],
    ])('validates stickiness %s', (_case, intervalCount, expected) => {
        const tool = GENERATED_TOOLS['query-stickiness']!()

        expect(tool.schema.safeParse({ ...insightQueries[3][1], intervalCount }).success).toBe(expected)
    })
})
