import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'

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

    it.each([
        ['zero interval count', 0, false],
        ['one interval', 1, true],
    ])('validates stickiness %s', (_case, intervalCount, expected) => {
        const tool = GENERATED_TOOLS['query-stickiness']!()

        expect(tool.schema.safeParse({ ...insightQueries[3][1], intervalCount }).success).toBe(expected)
    })

    // Shapes a saved FunnelsQuery carries that the wrapper used to reject, which stopped a caller
    // from replaying a saved funnel through the typed tool.
    const savedFunnelCases: [string, Record<string, unknown>][] = [
        ['default step math', { series: [{ kind: 'EventsNode', event: 'signed up', math: 'total' }] }],
        ['an action step without a name', { series: [{ kind: 'ActionsNode', id: 42 }] }],
        [
            'a numeric threshold filter',
            {
                series: [
                    {
                        kind: 'EventsNode',
                        event: 'order placed',
                        properties: [{ type: 'event', key: 'cart_total', operator: 'gte', value: 25 }],
                    },
                ],
            },
        ],
        [
            'a custom aggregation expression',
            {
                series: [{ kind: 'EventsNode', event: 'signed up' }],
                funnelsFilter: { funnelAggregateByHogQL: 'distinct_id' },
            },
        ],
    ]

    it.each(savedFunnelCases)('accepts a saved funnel with %s', (_case, { series, ...rest }) => {
        const tool = GENERATED_TOOLS['query-funnel']!()
        const savedFunnel = {
            kind: 'FunnelsQuery',
            series: [{ kind: 'EventsNode', event: '$pageview' }, ...(series as unknown[])],
            ...rest,
        }

        expect(tool.schema.safeParse(savedFunnel).success).toBe(true)
    })

    it('keeps a saved funnel unaggregated when it has no group type', () => {
        const tool = GENERATED_TOOLS['query-funnel']!()

        // `z.coerce.number()` reads an explicit null as 0, which silently aggregates the funnel by
        // the first group type instead of by persons.
        const parsed = tool.schema.parse({
            kind: 'FunnelsQuery',
            series: [
                { kind: 'EventsNode', event: '$pageview' },
                { kind: 'EventsNode', event: 'signed up' },
            ],
            aggregation_group_type_index: null,
        })

        expect(parsed.aggregation_group_type_index).toBeNull()
    })
})
