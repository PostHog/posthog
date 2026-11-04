import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react-native'
import type { ReactElement } from 'react'

import type { MetricView } from '@/model/types'

import { ObservationCard } from './ObservationCard'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'demo' }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

const BASE: MetricView = {
    metricId: 'errors',
    role: 'primary',
    title: 'TypeErrors in ChartLegend',
    format: { valueFormat: 'count', unit: null },
    chart: 'bar',
    interval: 'day',
    data: { kind: 'none' },
    windowLabel: 'Last 14 days',
    filterCount: 1,
}
let client: QueryClient

function renderCard(metric: MetricView): void {
    const tree: ReactElement = (
        <QueryClientProvider client={client}>
            <ObservationCard metric={metric} reportId="report-1" accent="alert" />
        </QueryClientProvider>
    )
    render(tree)
}

describe('ObservationCard', () => {
    beforeEach(() => {
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
    })

    afterEach(() => client.clear())

    test.each<[string, MetricView, string]>([
        [
            'static data',
            {
                ...BASE,
                data: {
                    kind: 'static',
                    value: 3721,
                    series: { interval: 'day', points: [{ at: '2026-10-13', value: 3721 }] },
                },
            },
            '3,721',
        ],
        [
            'a redacted metric with a saved series',
            { ...BASE, snapshot: { value: 612, at: null, series: [300, 312] } },
            '612',
        ],
    ])('shows the value and draws the chart for %s', (_name, metric, value) => {
        renderCard(metric)
        expect(screen.getByTestId('report-observation-value')).toHaveTextContent(value)
        expect(screen.getByTestId('report-observation-chart')).toBeTruthy()
        expect(screen.getByText('Last 14 days · 1 filter')).toBeTruthy()
    })

    test('draws no empty chart when there is no series at all', () => {
        renderCard({ ...BASE, snapshot: { value: 612, at: null, series: [] } })
        expect(screen.queryByTestId('report-observation-chart')).toBeNull()
    })
})
