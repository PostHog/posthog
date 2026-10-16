import { describe, expect, it } from 'vitest'

import {
    MarketingAnalyticsConversionGoalsApplyCreateBody,
    MarketingAnalyticsConversionGoalsPreviewCreateBody,
} from '@/generated/marketing_analytics/api'
import { GENERATED_TOOLS } from '@/tools/generated/marketing_analytics'

describe('Marketing conversion goal tool schemas', () => {
    const baseGoal = { conversion_goal_id: 'preview', conversion_goal_name: 'Paid purchase', schema_map: {} }
    const eventGoal = {
        ...baseGoal,
        kind: 'EventsNode',
        event: 'purchase',
        math: 'sum',
        math_property: 'amount',
        counts_as_revenue: true,
        math_property_revenue_currency: { property: 'currency', static: null },
        properties: [
            { type: 'event', key: 'refunded', operator: 'exact', value: false },
            { type: 'person', key: 'plan', operator: 'exact', value: ['paid'] },
            {
                type: 'behavioral',
                key: 'purchase',
                event_type: 'events',
                value: 'performed_event',
                time_interval: 'day',
                time_value: 30,
                event_filters: [{ type: 'event', key: 'amount', operator: 'gt', value: 0 }],
            },
        ],
        fixedProperties: [{ type: 'cohort', key: 'id', operator: 'in', value: 12, cohort_name: 'Customers' }],
        version: 1,
    }
    const goals = [
        eventGoal,
        {
            ...baseGoal,
            kind: 'ActionsNode',
            id: 42,
            math: 'dau',
            counts_as_customer: true,
            properties: [{ type: 'hogql', key: 'properties.amount > 0' }],
            fixedProperties: [
                {
                    type: 'group',
                    key: 'plan',
                    operator: 'exact',
                    value: 'paid',
                    group_type_index: 0,
                    group_key_names: { account: 'Account' },
                },
            ],
        },
        {
            ...baseGoal,
            kind: 'DataWarehouseNode',
            id: '00000000-0000-4000-8000-000000000001',
            table_name: 'paid_orders',
            id_field: 'order_id',
            distinct_id_field: 'customer_id',
            timestamp_field: 'paid_at',
            math: 'sum',
            math_property: 'amount',
            counts_as_revenue: true,
            math_property_revenue_currency: { static: 'USD' },
            properties: [{ type: 'data_warehouse', key: 'status', operator: 'exact', value: 'paid' }],
        },
    ]

    describe.each([
        {
            toolName: 'marketing-analytics-preview-conversion-goal',
            body: { date_from: '2026-10-01T00:00:00Z', date_to: '2026-10-08T00:00:00Z' },
            originalSchema: MarketingAnalyticsConversionGoalsPreviewCreateBody,
        },
        {
            toolName: 'marketing-analytics-apply-conversion-goal',
            body: { preview_ref: '00000000-0000-4000-8000-000000000002', definition_confirmed: true },
            originalSchema: MarketingAnalyticsConversionGoalsApplyCreateBody,
        },
    ])('$toolName', ({ toolName, body, originalSchema }) => {
        const schema = GENERATED_TOOLS[toolName]!().schema

        it.each(goals)('preserves the complete $kind draft and its filters', (goal) => {
            const input = { ...body, goal }
            const parsed = schema.parse(input)
            expect(parsed.goal).toEqual(goal)
            expect(parsed).toEqual(originalSchema().parse(input))
        })

        it('keeps generated defaults for a minimally specified event filter', () => {
            const input = { ...body, goal: { ...baseGoal, properties: [{ key: 'amount', value: 10 }] } }
            expect(schema.parse(input)).toEqual(originalSchema().parse(input))
            expect(schema.parse(input).goal).toMatchObject({
                kind: 'EventsNode',
                properties: [{ type: 'event', key: 'amount', operator: 'exact', value: 10 }],
            })
        })

        it.each([
            ['invalid filter operator', { properties: [{ type: 'event', key: 'amount', operator: 'unsupported' }] }],
            ['invalid currency', { math_property_revenue_currency: { static: 'INVALID' } }],
            ['invalid aggregation', { math: 'unsupported' }],
            ['invalid action ID', { kind: 'ActionsNode', id: '42' }],
            ['missing warehouse fields', { kind: 'DataWarehouseNode', id: 'table-id' }],
        ])('rejects %s using the full generated contract', (_label, invalidFields) => {
            const input = { ...body, goal: { ...eventGoal, ...invalidFields } }
            expect(originalSchema().safeParse(input).success).toBe(false)
            expect(schema.safeParse(input).success).toBe(false)
        })
    })
})
