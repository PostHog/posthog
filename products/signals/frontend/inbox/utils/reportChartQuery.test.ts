import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'

import { reportChartGraphQuery } from './reportChartQuery'

const CHART: ReportChartApi = {
    chart_id: 'signups-drop',
    title: 'Daily signups',
    query: null,
    caption: null,
    size: null,
}

describe('reportChartGraphQuery', () => {
    it.each([
        ['a trends line', { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } }, true],
        [
            'a trends number',
            {
                kind: 'InsightVizNode',
                source: { kind: 'TrendsQuery', series: [], trendsFilter: { display: 'BoldNumber' } },
            },
            false,
        ],
        ['a retention grid', { kind: 'InsightVizNode', source: { kind: 'RetentionQuery' } }, false],
        ['a SQL line', { kind: 'DataVisualizationNode', source: {}, display: 'ActionsLineGraph' }, true],
        ['a SQL number', { kind: 'DataVisualizationNode', source: {}, display: 'BoldNumber' }, false],
    ])('treats %s as a graph for a compact surface: %s', (_, query, isGraph) => {
        expect(reportChartGraphQuery({ ...CHART, query }) !== null).toBe(isGraph)
    })
})
