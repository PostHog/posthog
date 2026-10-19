import { useValues } from 'kea'

import { createDefaultTooltipAccessor, hoverUntilTooltip, renderHogChart } from '@posthog/quill-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'

import { DashboardMetricChart } from './DashboardMetricChart'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ loadData: jest.fn(), setChartMode: jest.fn(), setFocusedBreakdownValue: jest.fn() }),
}))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: () => ({}) }))
jest.mock('../marketingDashboardLogic', () => ({ marketingDashboardLogic: {} }))

describe('DashboardMetricChart', () => {
    it('displays percentage query results without scaling them a second time', async () => {
        const days = ['2026-01-01', '2026-01-02', '2026-01-03']
        jest.mocked(useValues).mockReturnValue({
            expandedMetricSpec: { label: 'New visitor share', format: 'percentage' },
            metricChartQuery: { kind: NodeKind.TrendsQuery, series: [] },
            chartMode: 'total',
            focusedBreakdownValue: null,
            breakdownLabel: 'Channel',
            timezone: 'UTC',
            response: { results: [{ days, data: [0, 42, 100] }] },
            responseLoading: false,
            responseError: null,
        })
        const { chart, container } = renderHogChart(<DashboardMetricChart />, { nativeTooltip: true })
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 1, days.length))

        expect(tooltip.value('New visitor share')).toBe('42.0%')
        expect(container.textContent).toContain('100.0%')
    })
})
