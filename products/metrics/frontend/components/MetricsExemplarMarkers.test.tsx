import '@testing-library/jest-dom'

import { cleanup, fireEvent, screen } from '@testing-library/react'

import { dimensions, makeOverlayContext, renderOverlayInChart } from '@posthog/quill-charts/testing'

import { MetricsExemplarMarkers } from './MetricsExemplarMarkers'

// jsdom has no stylesheet to resolve real color vars from, so both tokens would
// otherwise fall back to the same value — mock the lookup so per-marker colors
// (e.g. error spikes using 'danger') are distinguishable in assertions below.
// jsdom's style setter rejects `var(...)` as an inline value, so map to plain
// hex colors instead of round-tripping the token name.
jest.mock('lib/colors', () => ({
    getColorVar: (variable: string) => (variable === 'danger' ? '#ff0000' : '#0000ff'),
}))

// Three hourly buckets, laid out 100px apart, so an interpolated x is checkable by eye.
const BUCKETS = ['2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', '2026-08-01T12:00:00Z']
const BUCKET_X: Record<string, number> = { [BUCKETS[0]]: 100, [BUCKETS[1]]: 200, [BUCKETS[2]]: 300 }
const RADIUS = 4

function renderMarkers(timestamps: string[], onClick: () => void = jest.fn()): void {
    renderOverlayInChart(
        <MetricsExemplarMarkers
            exemplars={timestamps.map((timestamp) => ({
                timeMs: Date.parse(timestamp),
                onClick,
                tooltipLabel: `test exemplar at ${timestamp}`,
            }))}
        />,
        makeOverlayContext(
            { x: (label) => BUCKET_X[label], y: (value) => value, yTicks: () => [] },
            {
                labels: BUCKETS,
            }
        )
    )
}

function markerLefts(): number[] {
    return screen.queryAllByTestId('metrics-exemplar-marker').map((dot) => parseFloat((dot as HTMLElement).style.left))
}

describe('MetricsExemplarMarkers', () => {
    afterEach(() => cleanup())

    it.each([
        ['on the first bucket', '2026-08-01T10:00:00Z', 100],
        ['a quarter into the first bucket', '2026-08-01T10:15:00Z', 125],
        ['halfway between buckets', '2026-08-01T11:30:00Z', 250],
        ['on the last bucket', '2026-08-01T12:00:00Z', 300],
        // The last label marks the final bucket's start, not its end — an exemplar inside that
        // still-open bucket must clamp to the bucket's position rather than being dropped.
        ['inside the final (partial) bucket', '2026-08-01T12:30:00Z', 300],
    ])('positions an exemplar %s', (_, timestamp, expectedX) => {
        renderMarkers([timestamp])
        expect(markerLefts()).toEqual([expectedX - RADIUS])
    })

    // Exemplars are fetched over the requested window, not the plotted grid, so a stale or
    // wider-window response must not pile dots onto the first and last buckets.
    it.each([
        ['before the first bucket', '2026-08-01T09:59:00Z'],
        ['a bucket span past the last bucket', '2026-08-01T13:00:01Z'],
    ])('drops an exemplar %s instead of clamping it to the edge', (_, timestamp) => {
        renderMarkers([timestamp])
        expect(screen.queryAllByTestId('metrics-exemplar-marker')).toHaveLength(0)
    })

    it('clamps an exemplar onto a single-bucket chart instead of dropping it', () => {
        renderOverlayInChart(
            <MetricsExemplarMarkers
                exemplars={[{ timeMs: Date.parse('2026-08-01T10:30:00Z'), onClick: jest.fn(), tooltipLabel: 'test' }]}
            />,
            makeOverlayContext(
                { x: (label) => BUCKET_X[label], y: (value) => value, yTicks: () => [] },
                { labels: [BUCKETS[0]] }
            )
        )
        expect(markerLefts()).toEqual([100 - RADIUS])
    })

    it('pins dots to the plot baseline', () => {
        renderMarkers([BUCKETS[1]])
        const dot = screen.getByTestId('metrics-exemplar-marker')
        expect(dot.style.top).toBe(`${dimensions.plotTop + dimensions.plotHeight - RADIUS}px`)
    })

    it('opens the trace behind a clicked exemplar', () => {
        const onClick = jest.fn()
        renderMarkers([BUCKETS[1]], onClick)
        fireEvent.click(screen.getByTestId('metrics-exemplar-marker'))
        expect(onClick).toHaveBeenCalledTimes(1)
    })

    // Regression: error-spike markers sharing this overlay with trace exemplars
    // must render in their own color, or the two kinds become visually identical.
    it('uses a marker-specific color when provided, and the default otherwise', () => {
        renderOverlayInChart(
            <MetricsExemplarMarkers
                exemplars={[
                    { timeMs: Date.parse(BUCKETS[0]), onClick: jest.fn(), tooltipLabel: 'default color' },
                    {
                        timeMs: Date.parse(BUCKETS[1]),
                        onClick: jest.fn(),
                        color: 'danger',
                        tooltipLabel: 'danger color',
                    },
                ]}
            />,
            makeOverlayContext(
                { x: (label) => BUCKET_X[label], y: (value) => value, yTicks: () => [] },
                { labels: BUCKETS }
            )
        )
        const [defaultDot, coloredDot] = screen.getAllByTestId('metrics-exemplar-marker')
        expect(defaultDot.style.borderColor).toBe('#0000ff')
        expect(coloredDot.style.borderColor).toBe('#ff0000')
    })

    // A screen-reader user tells markers apart only by aria-label, so it must match each
    // marker's own content rather than a shared or hardcoded label.
    it('labels each marker with its own tooltip text', () => {
        renderOverlayInChart(
            <MetricsExemplarMarkers
                exemplars={[
                    { timeMs: Date.parse(BUCKETS[0]), onClick: jest.fn(), tooltipLabel: 'Traced emission' },
                    { timeMs: Date.parse(BUCKETS[1]), onClick: jest.fn(), tooltipLabel: 'Error spike: checkout' },
                ]}
            />,
            makeOverlayContext(
                { x: (label) => BUCKET_X[label], y: (value) => value, yTicks: () => [] },
                { labels: BUCKETS }
            )
        )
        expect(screen.getByLabelText('Traced emission')).toBeInTheDocument()
        expect(screen.getByLabelText('Error spike: checkout')).toBeInTheDocument()
    })

    it('renders nothing when the chart has no buckets yet', () => {
        renderOverlayInChart(
            <MetricsExemplarMarkers
                exemplars={[{ timeMs: Date.parse(BUCKETS[0]), onClick: jest.fn(), tooltipLabel: 'test' }]}
            />,
            makeOverlayContext({ x: () => undefined, y: (value) => value, yTicks: () => [] }, { labels: [] })
        )
        expect(screen.queryAllByTestId('metrics-exemplar-marker')).toHaveLength(0)
    })
})
