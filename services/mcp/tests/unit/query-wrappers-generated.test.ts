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

    // Saved retention insights written before the assistant schema gained `id` carry the event
    // name in `name`, and `insight-get` returns them that way. Replaying one must not need the
    // caller to rebuild the entity.
    const savedLegacyRetentionFilter = {
        period: 'Week',
        targetEntity: { name: 'user signed up', type: 'events' },
        returningEntity: { name: 'user signed up', type: 'events' },
    }

    it('runs a saved retention query whose entities carry only a name', () => {
        const tool = GENERATED_TOOLS['query-retention']!()

        const parsed = tool.schema.safeParse({ retentionFilter: savedLegacyRetentionFilter })

        expect(parsed.success).toBe(true)
        expect((parsed.data as any).retentionFilter.targetEntity.id).toBe('user signed up')
        expect((parsed.data as any).retentionFilter.returningEntity.id).toBe('user signed up')
    })

    it('drills into the cohort of a saved retention query whose entities carry only a name', () => {
        const tool = GENERATED_TOOLS['query-retention-actors']!()

        const parsed = tool.schema.safeParse({
            source: { retentionFilter: savedLegacyRetentionFilter },
            selectedInterval: 0,
        })

        expect(parsed.success).toBe(true)
        expect((parsed.data as any).source.retentionFilter.targetEntity.id).toBe('user signed up')
    })

    it.each([
        ['an explicit null id, which the engine reads as any event', { id: null, name: 'All events', type: 'events' }],
        ['an action, whose numeric id a name cannot stand in for', { name: 'Signed up', type: 'actions' }],
    ])('still rejects %s', (_case, targetEntity) => {
        const tool = GENERATED_TOOLS['query-retention']!()

        expect(
            tool.schema.safeParse({
                retentionFilter: { ...savedLegacyRetentionFilter, targetEntity },
            }).success
        ).toBe(false)
    })

    it('still requires an entity id from callers writing a new retention query', () => {
        const schema = z.toJSONSchema(GENERATED_TOOLS['query-retention']!().schema, {
            io: 'input',
            reused: 'inline',
        })

        const targetEntity = (schema.properties?.retentionFilter as any).properties.targetEntity
        for (const variant of targetEntity.anyOf) {
            expect(variant.required).toContain('id')
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
