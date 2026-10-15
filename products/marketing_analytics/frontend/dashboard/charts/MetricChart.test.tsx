import {
    clickAtIndex,
    createDefaultTooltipAccessor,
    hoverUntilTooltip,
    renderHogChart,
} from '@posthog/quill-charts/testing'

import { MetricChart, MetricChartProps } from './MetricChart'

const props: MetricChartProps = {
    label: 'Visitors',
    breakdownLabel: 'Channel',
    format: 'number',
    timezone: 'UTC',
    labels: ['2026-01-01', '2026-01-02', '2026-01-03'],
    series: [],
    chartMode: 'breakdown',
    focusedBreakdownValue: null,
    loading: false,
    error: null,
    onChartModeChange: jest.fn(),
    onFocus: jest.fn(),
}

describe('MetricChart', () => {
    it.each([
        { key: 'email', label: 'Email newsletter' },
        { key: '', label: 'No channel' },
    ])('selects the closest of several lines using the raw key "$key"', async ({ key, label }) => {
        const onFocus = jest.fn()
        const { chart } = renderHogChart(
            <MetricChart
                {...props}
                series={[
                    { key: 'lower', label: 'Lower line', data: [0, 0, 0] },
                    { key, label, data: [100, 100, 100] },
                    { key: 'upper', label: 'Upper line', data: [200, 200, 200] },
                ]}
                onFocus={onFocus}
            />,
            { nativeTooltip: true }
        )

        await clickAtIndex(chart.element, 1, props.labels.length)

        expect(onFocus).toHaveBeenCalledWith(key)
    })

    it('formats fractional rates as percentages in the axis and tooltip', async () => {
        const { chart, container } = renderHogChart(
            <MetricChart
                {...props}
                format="percentage"
                series={[{ key: 'email', label: 'Email', data: [0, 0.42, 1] }]}
            />,
            { nativeTooltip: true }
        )
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 1, props.labels.length))

        expect(tooltip.value('Email')).toBe('42.0%')
        expect(container.textContent).toContain('100.0%')
    })

    it('shows the supplied error instead of stale data and hides it during retry', () => {
        const { container, rerender, getByText, queryByText } = renderHogChart(
            <MetricChart {...props} series={[{ key: 'email', label: 'Email', data: [0, 12, 8] }]} />,
            { nativeTooltip: true }
        )
        rerender(
            <MetricChart
                {...props}
                series={[{ key: 'email', label: 'Email', data: [0, 12, 8] }]}
                error={<span>Query ID: synthetic-query-id</span>}
            />
        )

        expect(getByText('Query ID: synthetic-query-id')).not.toBeNull()
        expect(container.querySelector('canvas')).toBeNull()

        rerender(<MetricChart {...props} loading error={<span>Query ID: synthetic-query-id</span>} />)

        expect(queryByText('Query ID: synthetic-query-id')).toBeNull()
        expect(container.querySelector('[aria-label="Loading chart"]')).not.toBeNull()
    })
})
