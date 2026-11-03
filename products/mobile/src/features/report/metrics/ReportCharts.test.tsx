import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react-native'
import type { ReactElement } from 'react'

import type { MetricData, MetricView, ReportChartView } from '@/model/types'
import { ChartCanvasBudget, MAX_MOUNTED_CANVASES } from '@/ui/chart/budget/ChartCanvasBudget'

import { ObservationCard } from './ObservationCard'
import { ReportCharts } from './ReportCharts'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'demo' }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

const data: MetricData = {
    kind: 'static',
    value: 4,
    series: { interval: 'day', points: [{ at: '2026-10-13', value: 4 }] },
}
const charts: ReportChartView[] = Array.from({ length: 20 }, (_, index) => ({
    chartId: `chart-${index}`,
    title: `Chart ${index}`,
    chart: 'line',
    interval: 'day',
    format: { valueFormat: 'number', unit: null },
    data,
}))
const observation: MetricView = {
    metricId: 'observation',
    role: 'primary',
    title: 'Affected sessions',
    chart: 'bar',
    interval: 'day',
    format: { valueFormat: 'count', unit: null },
    windowLabel: 'Current window',
    filterCount: 0,
    data,
}

describe('ReportCharts', () => {
    test('shares the canvas limit with the observation and releases every canvas when inactive', () => {
        const client = new QueryClient()
        const report = (active: boolean): ReactElement => (
            <QueryClientProvider client={client}>
                <ChartCanvasBudget active={active}>
                    <ObservationCard metric={observation} reportId="report-1" accent="alert" />
                    <ReportCharts charts={charts} reportId="report-1" accent="alert" />
                </ChartCanvasBudget>
            </QueryClientProvider>
        )
        const canvases = /^report-(chart-.*-canvas|observation-chart)$/
        const placeholders = /^report-(chart-.*-canvas|observation-chart)-placeholder$/
        const view = render(report(true))
        try {
            expect(screen.getAllByTestId(canvases)).toHaveLength(MAX_MOUNTED_CANVASES)
            expect(screen.getByTestId('report-observation-chart')).toBeTruthy()
            expect(screen.getAllByTestId(placeholders, { includeHiddenElements: true })).toHaveLength(
                21 - MAX_MOUNTED_CANVASES
            )
            expect(screen.getByText('Chart 19')).toBeTruthy()
            view.rerender(report(false))
            expect(screen.queryAllByTestId(canvases)).toHaveLength(0)
            expect(screen.getAllByTestId(placeholders, { includeHiddenElements: true })).toHaveLength(21)
            view.rerender(report(true))
            expect(screen.getAllByTestId(canvases)).toHaveLength(MAX_MOUNTED_CANVASES)
        } finally {
            view.unmount()
            client.clear()
        }
    })
})
