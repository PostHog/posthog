import { HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { modelRowLabels } from '../aiLabs'
import { buildModelExplorationQuery, freezeModelDateRange, summarizeModelBreakdown } from './modelBreakdown'

describe('model breakdown', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('keeps unknown calls in coverage and the denominator while ranking named models in a stable order', () => {
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
        expect(summary.rankedModels).toEqual([rows[3], rows[2], { model: 'Other models', total_calls: 30 }])
        expect(summary.rankedModels[0].total_calls / summary.totalCalls).toBe(0.15)
        expect(rows[0].model).toBe('Unknown')

        const tiedRows = [
            { model: 'example-zeta', total_calls: 10 },
            { model: 'example-alpha', total_calls: 10 },
        ]
        const tiedRowLabels = new Map(tiedRows.map(({ model }) => [model, model]))

        expect(summarizeModelBreakdown(tiedRows, tiedRowLabels).rankedModels.map(({ model }) => model)).toEqual([
            'example-alpha',
            'example-zeta',
        ])
    })

    it('names the top models and lone leftovers, and folds the rest into one row per AI lab', () => {
        const rows = [
            { model: 'claude-opus-5-5', total_calls: 70 },
            { model: 'gpt-6', total_calls: 60 },
            { model: 'gpt-6-astra', total_calls: 50 },
            { model: 'claude-fable-5-1', total_calls: 40 },
            { model: 'grok-4.7', total_calls: 30 },
            { model: 'claude-sonnet-5', total_calls: 20 },
            { model: 'claude-haiku-5', total_calls: 3 },
            { model: 'claude-opus-4-8', total_calls: 2 },
            { model: 'gpt-5', total_calls: 4 },
            { model: 'example-custom-model', total_calls: 9 },
            { model: 'Other', total_calls: 1 },
        ]

        const top = new Set(rows.slice(0, 6).map((row) => row.model))
        const rowLabels = modelRowLabels(
            rows.map((row) => row.model),
            top
        )

        expect(
            summarizeModelBreakdown(rows, rowLabels).rankedModels.map(({ model, total_calls }) => [model, total_calls])
        ).toEqual([
            ['claude-opus-5-5', 70],
            ['gpt-6', 60],
            ['gpt-6-astra', 50],
            ['claude-fable-5-1', 40],
            ['grok-4.7', 30],
            ['claude-sonnet-5', 20],
            ['gpt-5', 4],
            ['Other Anthropic models', 5],
            ['Other models', 10],
        ])
    })

    it('puts a model in the row the page chose, even when this chart alone would name it', () => {
        const rows = [
            { model: 'claude-opus-5-5', total_calls: 70 },
            { model: 'gemini-3-flash', total_calls: 3 },
        ]
        const pageRowLabels = new Map([
            ['claude-opus-5-5', 'claude-opus-5-5'],
            ['gemini-3-flash', 'Other Google models'],
        ])

        expect(summarizeModelBreakdown(rows, pageRowLabels).rankedModels.map((row) => row.model)).toEqual([
            'claude-opus-5-5',
            'Other Google models',
        ])
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
        const visualization = buildModelExplorationQuery(filters)

        expect(visualization.kind).toBe(NodeKind.InsightVizNode)
        const query = visualization.source
        expect(query.kind).toBe(NodeKind.TrendsQuery)

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

    it.each([
        ['a date-only end', { date_from: '2026-09-01', date_to: '2026-09-05' }, {}],
        ['a relative end', { date_from: '-14d', date_to: '-7d' }, {}],
        [
            'an end with a time of day',
            { date_from: '2026-09-01T00:00:00Z', date_to: '2026-09-05T15:00:00Z' },
            { explicitDate: true },
        ],
    ])('keeps a fixed range with %s, marking exact times explicit', (_, dateRange, extra) => {
        expect(freezeModelDateRange(dateRange, 'America/Los_Angeles')).toEqual({ ...dateRange, ...extra })
    })
})
