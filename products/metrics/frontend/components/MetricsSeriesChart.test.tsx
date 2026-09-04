import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import {
    createDefaultTooltipAccessor,
    ensureJsdom,
    getHogChart,
    hoverUntilTooltip,
} from '@posthog/quill-charts/testing'

import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { MetricsExemplar } from './MetricsExemplarMarkers'
import type { MetricsChartSeries } from './metricsSeries'
import { MetricsSeriesChart } from './MetricsSeriesChart'

const BUCKETS = ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', '2026-08-01T12:00:00Z']

function seriesWith(labels: Record<string, string>, values: (number | null)[]): MetricsChartSeries {
    return { labels, points: BUCKETS.map((time, i) => ({ time, value: values[i] })) }
}

function renderChart(
    series: MetricsChartSeries[],
    exemplars?: MetricsExemplar[],
    display?: MetricsDisplaySettings
): void {
    render(<MetricsSeriesChart series={series} fallbackName="http.requests" exemplars={exemplars} display={display} />)
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
        renderChart(
            [seriesWith({}, [1, 2, 3])],
            [{ timeMs: Date.parse(BUCKETS[1]), onClick: jest.fn(), tooltipLabel: 'test exemplar' }]
        )
        expect(screen.getAllByTestId('metrics-exemplar-marker')).toHaveLength(1)
    })

    // `stat` is in the schema union but has no renderer yet, so it must degrade to a line chart
    // rather than blanking a saved tile.
    it.each([
        ['renders no display as a line chart', undefined, 'line'],
        ['renders the area display as a line chart', 'area' as const, 'line'],
        ['renders the bar display as a bar chart', 'bar' as const, 'bar'],
        ['degrades the unimplemented stat display to a line chart', 'stat' as const, 'line'],
    ])('%s', (_name, type, expectedChart) => {
        renderChart([seriesWith({ service: 'a' }, [1, 2, 3]), seriesWith({ service: 'b' }, [4, 5, 6])], undefined, {
            type,
        })

        expect(getHogChart().seriesCount).toBe(2)
        expect(screen.getByTestId(`hog-chart-timeseries-${expectedChart}-legend`)).toBeInTheDocument()
    })

    // The exemplar overlay reads the chart's layout context, which throws when it isn't nested
    // under a chart provider — so a bar chart that forgot to pass children through is a hard crash.
    it('keeps exemplar markers working on the bar display', () => {
        renderChart(
            [seriesWith({}, [1, 2, 3])],
            [{ timeMs: Date.parse(BUCKETS[1]), onClick: jest.fn(), tooltipLabel: 'test exemplar' }],
            { type: 'bar' }
        )
        expect(screen.getAllByTestId('metrics-exemplar-marker')).toHaveLength(1)
    })

    it('draws a goal line above the data', () => {
        renderChart([seriesWith({}, [1, 2, 3])], undefined, {
            goalLines: [{ label: 'SLO', value: 10 }],
        })
        expect(screen.getByText('SLO')).toBeInTheDocument()
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
