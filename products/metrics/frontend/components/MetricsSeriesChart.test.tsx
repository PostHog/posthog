import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import {
    createDefaultTooltipAccessor,
    ensureJsdom,
    getHogChart,
    hoverUntilTooltip,
} from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import type { MetricsChartSeries } from './metricsSeries'
import { MetricsSeriesChart } from './MetricsSeriesChart'

const BUCKETS = ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', '2026-08-01T12:00:00Z']

function seriesWith(labels: Record<string, string>, values: (number | null)[]): MetricsChartSeries {
    return { labels, points: BUCKETS.map((time, i) => ({ time, value: values[i] })) }
}

function renderChart(series: MetricsChartSeries[], exemplars?: { timeMs: number; onClick: () => void }[]): void {
    render(<MetricsSeriesChart series={series} fallbackName="http.requests" exemplars={exemplars} />)
}

describe('MetricsSeriesChart', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('draws one line per series', () => {
        renderChart([seriesWith({ service: 'checkout' }, [1, 2, 3]), seriesWith({ service: 'billing' }, [4, 5, 6])])
        expect(getHogChart().seriesCount).toBe(2)
    })

    it.each([
        ['names a grouped series by its labels', { service: 'checkout', env: 'prod' }, 'service=checkout, env=prod'],
        ['falls back to the metric name when ungrouped', {}, 'http.requests'],
    ])('%s', (_, labels, expected) => {
        renderChart([seriesWith(labels, [1, 2, 3]), seriesWith({ service: 'billing' }, [4, 5, 6])])
        expect(screen.getByText(expected)).toBeInTheDocument()
    })

    it.each([
        ['hides the legend for a single series', 1, false],
        ['shows the legend once there are two', 2, true],
    ])('%s', (_, count, expected) => {
        renderChart(Array.from({ length: count }, (_, i) => seriesWith({ service: `svc-${i}` }, [1, 2, 3])))
        expect(!!screen.queryByTestId('hog-chart-timeseries-line-legend')).toBe(expected)
    })

    it('renders a clickable dot per traced exemplar', () => {
        renderChart([seriesWith({}, [1, 2, 3])], [{ timeMs: Date.parse(BUCKETS[1]), onClick: jest.fn() }])
        expect(screen.getAllByTestId('metrics-exemplar-marker')).toHaveLength(1)
    })

    // A null bucket is a non-representable aggregate. Charting it as 0 is the legacy behavior;
    // dropping the point instead would silently shift every later value a bucket to the left.
    it('charts a null bucket as zero rather than dropping the point', async () => {
        renderChart([seriesWith({}, [1, null, 3])])
        const chart = getHogChart()
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 1, BUCKETS.length))
        expect(tooltip.value('http.requests')).toBe('0')
    })

    // Guards createXAxisTickCallback and the tz-aware labelFormatter wiring: a regression here
    // renders raw ISO strings on every tick and tooltip header instead of formatted dates.
    it('formats the x-axis ticks and tooltip label as tz-aware dates', async () => {
        renderChart([seriesWith({}, [1, 2, 3])])
        const chart = getHogChart()
        expect(chart.xTicks()).toEqual(['10:00', '11:00', '12:00'])
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 1, BUCKETS.length))
        expect(tooltip.label()).toBe('1 Aug 2026 11:00:00')
    })
})
