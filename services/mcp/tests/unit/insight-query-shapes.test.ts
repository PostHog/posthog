import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

const BARE_TRENDS_QUERY = {
    kind: 'TrendsQuery',
    series: [{ kind: 'EventsNode', event: '$pageview', name: '$pageview' }],
    dateRange: { date_from: '-7d' },
    interval: 'day',
}

// Every shape `MCPInsightSerializer.validate_query` normalizes and saves. The bare ones are
// wrapped server-side, so the tool boundary has to pass them through rather than reject them.
const acceptedQueries = [
    {
        shape: 'wrapped InsightVizNode',
        query: { kind: 'InsightVizNode', source: BARE_TRENDS_QUERY },
    },
    {
        shape: 'wrapped DataVisualizationNode',
        query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } },
    },
    { shape: 'bare TrendsQuery', query: BARE_TRENDS_QUERY },
    { shape: 'bare HogQLQuery', query: { kind: 'HogQLQuery', query: 'select 1' } },
    {
        shape: 'bare WebStatsTableQuery',
        query: { kind: 'WebStatsTableQuery', breakdownBy: 'Page', properties: [], dateRange: { date_from: '-7d' } },
    },
]

// A saved SQL insight as insight-get returns it, with settings the assistant schema does not declare
// at every nesting level.
const SAVED_DATA_VISUALIZATION_NODE = {
    kind: 'DataVisualizationNode',
    version: 1,
    source: { kind: 'HogQLQuery', query: 'select day, country, count() from events group by day, country' },
    display: 'ActionsLineGraph',
    chartSettings: {
        xAxis: {
            column: 'day',
            savedAxisMetadata: true,
            settings: {
                savedSettingsMetadata: true,
                formatting: { prefix: '', savedFormattingMetadata: true },
                display: { label: 'Day', savedDisplayMetadata: true },
            },
        },
        yAxis: [
            {
                column: 'count()',
                settings: {
                    formatting: { style: 'number', decimalPlaces: 0 },
                    display: { color: '#1d4aff', yAxisPosition: 'left', displayType: 'line', trendLine: false },
                },
            },
        ],
        yAxisAtZero: true,
        leftYAxisSettings: { startAtZero: true, showGridLines: true },
        goalLines: [{ label: 'Target', value: 100, borderColor: '#ff0000', displayLabel: true, position: 'end' }],
        showAnnotations: false,
        showXAxisTicks: true,
        showXAxisBorder: false,
        showYAxisBorder: false,
        legendPosition: 'bottom',
        showPieTotal: true,
        pie: { sliceContent: 'values', valueDisplay: 'percentage', showTotal: false },
        scatter: { xScale: 'logarithmic', showBestFit: true },
        metric: { summary: 'total', showChange: false },
        heatmap: { xAxisColumn: 'day', yAxisColumn: 'country', gradientScaleMode: 'relative' },
        resultCustomizations: { US: { assignmentBy: 'value', color: 'preset-2' } },
        chartStyle: { curve: 'smooth' },
    },
    tableSettings: {
        columns: [{ column: 'day' }],
        conditionalFormatting: [
            { id: 'rule-1', templateId: 'tpl', columnName: 'count()', bytecode: [], input: '10', color: '#00ff00' },
        ],
        pinnedColumns: ['day'],
    },
}

const tools = [
    { tool: 'insight-create', base: {} },
    { tool: 'insight-update', base: { id: 1 } },
]

const cases = tools.flatMap(({ tool, base }) => acceptedQueries.map((accepted) => ({ tool, base, ...accepted })))

describe('insight query shapes', () => {
    it.each(cases)('$tool accepts a $shape', ({ tool, base, query }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        expect(schema.safeParse({ ...base, query }).success).toBe(true)
    })

    it.each(tools)('$tool sends a bare query on to the endpoint whole', ({ tool, base }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        const result = schema.safeParse({ ...base, query: BARE_TRENDS_QUERY })

        // The bare branches carry an index signature so the query keeps its body. Without it zod
        // strips every key it does not declare, and the insight saves as an empty TrendsQuery.
        expect(result.success).toBe(true)
        expect((result.data as { query: unknown }).query).toEqual(BARE_TRENDS_QUERY)
    })

    it.each(tools)('$tool keeps every setting of a saved DataVisualizationNode', ({ tool, base }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        const edited = {
            ...SAVED_DATA_VISUALIZATION_NODE,
            chartSettings: { ...SAVED_DATA_VISUALIZATION_NODE.chartSettings, showLegend: true },
        }
        const result = schema.safeParse({ ...base, query: edited })

        expect(result.success).toBe(true)
        expect((result.data as { query: unknown }).query).toEqual(edited)
    })

    it.each(tools)('$tool rejects a query kind the endpoint refuses to save', ({ tool, base }) => {
        const { schema } = GENERATED_TOOLS[tool]!()

        const query = { kind: 'ErrorTrackingQuery', dateRange: { date_from: '-7d' }, orderBy: 'last_seen' }

        expect(schema.safeParse({ ...base, query }).success).toBe(false)
    })
})
