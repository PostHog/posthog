import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportChart, reportChartGraphQuery } from './ReportChart'
import { ReportChartsContext } from './reportChartsContext'

jest.mock('~/queries/Query/Query', () => ({ Query: () => <div data-attr="query" /> }))

const CHART: ReportChartApi = {
    chart_id: 'signups-drop',
    title: 'Daily signups',
    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
    caption: null,
    size: 'medium',
}

describe('ReportChart', () => {
    it('draws the chart from the charts in context, without the Inbox detail logic', () => {
        render(
            <ReportChartsContext.Provider value={new Map([[CHART.chart_id, CHART]])}>
                <ReportChart chartId="signups-drop" />
            </ReportChartsContext.Provider>
        )

        expect(screen.getByText('Daily signups')).toBeInTheDocument()
    })

    it('draws nothing for a chart the report does not have', () => {
        const { container } = render(<ReportChart chartId="signups-drop" />)

        expect(container).toBeEmptyDOMElement()
    })

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
