import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

// Both tools take the query; only update also needs an id.
const cases = [
    { tool: 'insight-create', base: {} },
    { tool: 'insight-update', base: { id: 1 } },
]

const chartSettings = {
    showLegend: true,
    legendPosition: 'bottom',
    showAnnotations: true,
}

const query = {
    kind: 'DataVisualizationNode',
    source: { kind: 'HogQLQuery', query: 'select 1 as value, now() as day' },
    display: 'ActionsLineGraph',
    chartSettings,
}

// Zod drops object keys the schema does not declare, so a chart setting missing here is
// removed without an error and the insight saves without it.
describe('insight chart settings survive the advertised query schema', () => {
    it.each(cases)('$tool keeps the legend position and the annotation toggle', ({ tool, base }) => {
        const schema = GENERATED_TOOLS[tool]!().schema

        const result = schema.safeParse({ ...base, query })

        expect(result.success).toBe(true)
        expect((result.data as { query: typeof query }).query.chartSettings).toEqual(chartSettings)
    })
})
