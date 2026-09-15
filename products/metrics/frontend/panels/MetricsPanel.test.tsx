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

import type { MetricsExemplar } from '../components/MetricsExemplarMarkers'
import type { MetricsChartSeries } from '../components/metricsSeries'
import { MetricsPanel } from './MetricsPanel'

const BUCKETS = ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', '2026-08-01T12:00:00Z']

function seriesWith(
    labels: Record<string, string>,
    values: (number | null)[],
    metricName?: string,
    unit?: string
): MetricsChartSeries {
    return { labels, points: BUCKETS.map((time, i) => ({ time, value: values[i] })), metricName, unit }
}

function renderPanel(
    series: MetricsChartSeries[],
    display?: MetricsDisplaySettings,
    exemplars?: MetricsExemplar[]
): void {
    render(<MetricsPanel series={series} fallbackName="http.requests" display={display} exemplars={exemplars} />)
}

describe('MetricsPanel time-series (line/area/bar)', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('draws one line per series by default', () => {
        renderPanel([seriesWith({ service: 'checkout' }, [1, 2, 3]), seriesWith({ service: 'billing' }, [4, 5, 6])])
        expect(getHogChart().seriesCount).toBe(2)
    })

    it.each([
        ['renders no display as a line chart', undefined, 'line'],
        ['renders the area display as a line chart', 'area' as const, 'line'],
        ['renders the bar display as a bar chart', 'bar' as const, 'bar'],
    ])('%s', (_name, type, expectedChart) => {
        renderPanel([seriesWith({ service: 'a' }, [1, 2, 3]), seriesWith({ service: 'b' }, [4, 5, 6])], { type })
        expect(getHogChart().seriesCount).toBe(2)
        expect(screen.getByTestId(`hog-chart-timeseries-${expectedChart}-legend`)).toBeInTheDocument()
    })

    it('falls back to a line chart for an unknown display type', () => {
        renderPanel([seriesWith({ service: 'a' }, [1, 2, 3])], { type: 'pie' as never })
        expect(getHogChart().seriesCount).toBe(1)
    })

    it('renders a clickable dot per traced exemplar', () => {
        renderPanel([seriesWith({}, [1, 2, 3])], undefined, [
            { timeMs: Date.parse(BUCKETS[1]), onClick: jest.fn(), tooltipLabel: 'test exemplar' },
        ])
        expect(screen.getAllByTestId('metrics-exemplar-marker')).toHaveLength(1)
    })

    // A null bucket is a non-representable aggregate. quill draws only numbers, so it renders as 0
    // until the quill null-data change; dropping it would shift later values a bucket left.
    it('charts a null bucket as zero rather than dropping the point', async () => {
        renderPanel([seriesWith({}, [1, null, 3])])
        const chart = getHogChart()
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 1, BUCKETS.length))
        expect(tooltip.value('http.requests')).toBe('0')
    })

    it('draws a goal line above the data', () => {
        renderPanel([seriesWith({}, [1, 2, 3])], { goalLines: [{ label: 'SLO', value: 10 }] })
        expect(screen.getByText('SLO')).toBeInTheDocument()
    })
})

describe('MetricsPanel scalar and categorical panels', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('renders the stat headline with the resolved unit', () => {
        renderPanel([seriesWith({}, [100, 200, 340], 'http.duration', 'ms')], { type: 'stat' })
        expect(screen.getByText('340 ms')).toBeInTheDocument()
    })

    it('stat uses the reduce reducer', () => {
        renderPanel([seriesWith({}, [100, 200, 340], 'm', 'ms')], { type: 'stat', reduce: 'max' })
        expect(screen.getByText('340 ms')).toBeInTheDocument()
    })

    it('stat maps the deprecated statSummary', () => {
        renderPanel([seriesWith({}, [100, 200, 300], 'm', 'ms')], { type: 'stat', statSummary: 'average' })
        expect(screen.getByText('200 ms')).toBeInTheDocument()
    })

    it('renders one stat card per grouped series', () => {
        renderPanel([seriesWith({ service: 'a' }, [1, 2, 3]), seriesWith({ service: 'b' }, [4, 5, 6])], {
            type: 'stat',
        })
        expect(screen.getByText('service=a')).toBeInTheDocument()
        expect(screen.getByText('service=b')).toBeInTheDocument()
    })

    it('renders the table panel with label and reducer columns', () => {
        renderPanel([seriesWith({ service: 'api', pod: 'p1' }, [10, 20, 30])], { type: 'table', reduce: 'last' })
        expect(screen.getByText('service')).toBeInTheDocument()
        expect(screen.getByText('pod')).toBeInTheDocument()
        expect(screen.getByText('api')).toBeInTheDocument()
        expect(screen.getByText('30')).toBeInTheDocument()
    })

    it('renders the gauge arc with a formatted value and bounds', () => {
        renderPanel([seriesWith({}, [0, 0, 40], 'cpu', '%')], {
            type: 'gauge',
            yAxis: { min: 0, max: 100 },
        })
        expect(screen.getByText('40%')).toBeInTheDocument()
        expect(screen.getByText('0% – 100%')).toBeInTheDocument()
    })

    it('renders the bar gauge with one bar per grouped series', () => {
        renderPanel([seriesWith({ pod: 'a' }, [1, 2, 10]), seriesWith({ pod: 'b' }, [1, 2, 20])], { type: 'bargauge' })
        expect(getHogChart().seriesCount).toBe(1)
        expect(screen.getByText('pod=a')).toBeInTheDocument()
        expect(screen.getByText('pod=b')).toBeInTheDocument()
    })

    it('shows No data for an empty result on a scalar panel', () => {
        renderPanel([seriesWith({}, [])], { type: 'stat' })
        expect(screen.getByText('No data')).toBeInTheDocument()
    })
})
