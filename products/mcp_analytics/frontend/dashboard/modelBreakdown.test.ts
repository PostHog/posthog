import { HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { buildModelExplorationQuery, freezeModelDateRange, summarizeModelBreakdown } from './modelBreakdown'

describe('model breakdown', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('keeps unknown calls in coverage and the denominator while ranking named models before Other', () => {
        const rows = [
            { model: 'Unknown', total_calls: 50 },
            { model: 'Other', total_calls: 30 },
            { model: 'example-small', total_calls: 5 },
            { model: 'example-large', total_calls: 15 },
        ]
        const summary = summarizeModelBreakdown(rows)

        expect(summary.totalCalls).toBe(100)
        expect(summary.unknownCalls).toBe(50)
        expect(summary.identifiedShare).toBe(50)
        expect(summary.rankedModels).toEqual([rows[3], rows[2], rows[1]])
        expect(summary.rankedModels[0].total_calls / summary.totalCalls).toBe(0.15)
        expect(rows[0].model).toBe('Unknown')
    })

    it.each([
        { rows: [], totalCalls: 0, unknownCalls: 0, identifiedShare: 0 },
        {
            rows: [{ model: 'Unknown', total_calls: 12 }],
            totalCalls: 12,
            unknownCalls: 12,
            identifiedShare: 0,
        },
        {
            rows: [{ model: 'example-model', total_calls: 12 }],
            totalCalls: 12,
            unknownCalls: 0,
            identifiedShare: 100,
        },
    ])('handles coverage without both known and unknown calls: $rows', ({ rows, ...expected }) => {
        expect(summarizeModelBreakdown(rows)).toMatchObject(expected)
    })

    it('opens a model count table with the same date, property, and test-account filters', () => {
        const filters: HogQLFilters = {
            dateRange: { date_from: '-14d', date_to: null },
            filterTestAccounts: true,
            properties: [
                {
                    key: '$mcp_server_name',
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                    value: ['example-server'],
                },
            ],
        }
        const query = buildModelExplorationQuery(filters)

        expect(query).toMatchObject(filters)
        expect(query.series).toEqual([{ kind: NodeKind.EventsNode, event: '$mcp_tool_call', math: 'total' }])
        expect(query.breakdownFilter).toMatchObject({
            breakdown: "coalesce(nullIf(trim(toString(properties.$mcp_llm_model)), ''), 'Unknown')",
            breakdown_type: 'hogql',
        })
        expect(query.trendsFilter?.display).toBe('ActionsTable')
    })
    it.each([
        { date_from: '-14d', expectedFrom: '2026-08-28T07:00:00.000Z' },
        { date_from: '-1h', expectedFrom: '2026-09-11T14:00:00.000Z' },
        { date_from: 'all', expectedFrom: 'all' },
        { date_from: '2026-09-10T14:25:00Z', expectedFrom: '2026-09-10T14:25:00Z' },
    ])('freezes the open range $date_from in the project timezone', ({ date_from, expectedFrom }) => {
        jest.setSystemTime(new Date('2026-09-11T15:30:00Z'))
        expect(freezeModelDateRange({ date_from }, 'America/Los_Angeles')).toEqual({
            date_from: expectedFrom,
            date_to: '2026-09-11T15:30:00.000Z',
            explicitDate: true,
        })
    })

    it('preserves a fixed date range', () => {
        const dateRange = { date_from: '2026-09-01', date_to: '2026-09-05' }
        expect(freezeModelDateRange(dateRange, 'America/Los_Angeles')).toEqual(dateRange)
    })
})
