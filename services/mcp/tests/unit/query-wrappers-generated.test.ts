import { describe, expect, it } from 'vitest'

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
})
