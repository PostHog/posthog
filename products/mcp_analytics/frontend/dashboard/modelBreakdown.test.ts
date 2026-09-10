import { HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { buildModelExplorationQuery, summarizeModelBreakdown } from './modelBreakdown'

describe('model breakdown', () => {
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
        expect(query.breakdownFilter).toMatchObject({ breakdown: '$mcp_llm_model', breakdown_type: 'event' })
        expect(query.trendsFilter?.display).toBe('ActionsTable')
    })
})
