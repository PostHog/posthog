import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { ExportType } from '~/exporter/types'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    buildTrendsQuery,
    chart,
    createInsightTooltipAccessor,
    getHogChart,
    legend,
    personsModal,
    renderInsight,
} from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
import { AnnotationScope, ChartDisplayType } from '~/types'

// The full InsightViz tree is heavy to mount under jsdom; on contended CI shards
// the default 1s waitFor / findBy timeout is too tight and flakes randomly.
configure({ asyncUtilTimeout: 5000 })
// With asyncUtilTimeout at 5s, a single legitimate waitFor can exhaust Jest's default
// 5s per-test budget — the first test in the file (which also pays chart init) hits this.
jest.setTimeout(15000)

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    personsModal.cleanupAll()
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('TrendsLineChart', () => {
    describe('tooltips', () => {
        it('shows each series with its own value for multiple series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.row('Napped')).toContain('5')
        })

        it('sorts tooltip rows by descending value regardless of series order', async () => {
            // At index 2: Pageview=134, Napped=5, Minimal=1, NoActivity=0.
            // Input order, alphabetic, and value order all differ.
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                        { kind: NodeKind.EventsNode, event: 'Minimal', name: 'Minimal' },
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' },
                    ],
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            const rows = tooltip.rows()
            expect(rows[0]).toContain('Pageview')
            expect(rows[1]).toContain('Napped')
            expect(rows[2]).toContain('Minimal')
            expect(rows[3]).toContain('NoActivity')
            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.row('Napped')).toContain('5')
            expect(tooltip.row('Minimal')).toContain('1')
            expect(tooltip.row('NoActivity')).toContain('0')
        })

        it('shows breakdown values in the tooltip', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            // Breakdown data produces multiple series, so the chart requires a
            // click to pin the tooltip (hover alone won't render it).
            await chart.clickAtIndex(2)

            const tooltip = createInsightTooltipAccessor(chart.getTooltip()!)
            expect(tooltip.row('Spike')).toContain('3')
        })

        it('shows every breakdown value when a formula is applied', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    trendsFilter: { formula: 'A' },
                }),
            })

            await chart.clickAtIndex(2)

            const tooltip = createInsightTooltipAccessor(chart.getTooltip()!)
            expect(tooltip.row('Spike')).toContain('3')
            expect(tooltip.row('Bramble')).toContain('1')
            expect(tooltip.row('Prickles')).toContain('1')
        })

        it('shows current and previous period rows in compare mode', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    compareFilter: { compare: true },
                }),
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Current')).toContain('134')
            expect(tooltip.row('Previous')).toContain('100')
        })

        it('uses context.formatCompareLabel to override Current/Previous in compare mode', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    compareFilter: { compare: true },
                }),
                context: {
                    formatCompareLabel: (label) => (label === 'current' ? 'This week' : 'Last week'),
                },
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('This week')).toContain('134')
            expect(tooltip.row('Last week')).toContain('100')
            expect(tooltip.element.textContent).not.toContain('Current')
        })

        it('formats values as percentages in percent stack view', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsAreaGraph,
                        showPercentStackView: true,
                    },
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toMatch(/%/)
        })

        it('shows zero-count series alongside active ones', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('ActiveSeries')).toContain('3')
            expect(tooltip.row('EmptySeries')).toContain('0')
        })
    })

    describe('moving average overlay', () => {
        it('omits the moving-average series from tooltip rows', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        showMovingAverage: true,
                        movingAverageIntervals: 3,
                    },
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.textContent).not.toContain('Moving avg')
        })

        it('renders only the main series when disabled', async () => {
            renderInsight({ query: buildTrendsQuery() })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 1 data series/i)).toBeInTheDocument()
            })
        })
    })

    describe('annotations', () => {
        it('renders an annotation badge when an annotation exists', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mocks: {
                    annotations: [
                        buildAnnotation({
                            scope: AnnotationScope.Project,
                            content: 'Hedgehog spotted',
                            date_marker: '2024-06-12T12:00:00Z',
                        }),
                    ],
                },
            })

            await waitFor(() => {
                const badges = document.querySelectorAll('.AnnotationsBadge')
                expect(badges.length).toBeGreaterThan(0)
            })
        })

        it('does not render annotations when inSharedMode is true', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mocks: {
                    annotations: [
                        buildAnnotation({
                            scope: AnnotationScope.Project,
                            content: 'Hidden in shared mode',
                            date_marker: '2024-06-12T12:00:00Z',
                        }),
                    ],
                },
                inSharedMode: true,
            })

            await screen.findByLabelText(/chart with/i)
            expect(document.querySelectorAll('.AnnotationsBadge')).toHaveLength(0)
        })
    })

    describe('area chart', () => {
        it('renders the chart in area mode without crashing', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: { display: ChartDisplayType.ActionsAreaGraph },
                }),
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })
        })
    })

    describe('tooltip date title', () => {
        it('shows the hovered day in the tooltip title row', async () => {
            renderInsight({
                query: buildTrendsQuery({ interval: 'day' }),
            })

            const tooltip = await chart.hoverTooltip(2)

            // Wednesday is the third day (index 2) in our pageview fixture (2024-06-12).
            expect(tooltip.title()).toMatch(/Wednesday/i)
            expect(tooltip.title()).toMatch(/12.+Jun/)
        })
    })

    describe('alert overlays', () => {
        it('does not render any alert overlay for an unsaved insight (insight.id is missing)', async () => {
            renderInsight({
                query: buildTrendsQuery(),
            })

            await screen.findByLabelText(/chart with/i)
            // Reference lines come exclusively from goalLines in this test (none configured),
            // so the count must be 0 — anything here would be a leaked alert overlay.
            expect(getHogChart().referenceLines()).toHaveLength(0)
        })
    })

    describe('hidden series via legend', () => {
        it('excludes a hidden series from the tooltip', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                }),
            })

            // Wait for both series before toggling.
            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            await legend.toggle('Napped')

            const tooltip = await chart.hoverTooltip(2)
            expect(tooltip.row('Pageview')).toContain('134')
            expect(tooltip.element.textContent).not.toContain('Napped')
        })
    })

    describe('axis labels', () => {
        it('renders custom axis titles from the trends filter', async () => {
            renderInsight({
                query: buildTrendsQuery({ trendsFilter: { xAxisLabel: 'Signup date', yAxisLabel: 'Unique users' } }),
            })

            await screen.findByLabelText(/chart with/i)
            expect(getHogChart().xAxisLabel()).toBe('Signup date')
            expect(getHogChart().yAxisLabel()).toBe('Unique users')
        })
    })

    describe('multi-axis', () => {
        it('renders a right y-axis when showMultipleYAxes is true', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: { showMultipleYAxes: true },
                }),
            })

            await waitFor(() => {
                expect(getHogChart().hasRightAxis).toBe(true)
            })
            expect(getHogChart().yRightTicks().length).toBeGreaterThan(0)
        })
    })

    describe('goal lines', () => {
        it('single goal line renders with its label', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { goalLines: [{ label: 'Target', value: 150, displayIfCrossed: true }] },
                }),
            })

            await screen.findByLabelText(/chart with/i)
            await waitFor(
                () => {
                    const lines = getHogChart().referenceLines()
                    expect(lines.map((l) => l.label)).toEqual(['Target'])
                    for (const line of lines) {
                        expect(line.orientation).toBe('horizontal')
                    }
                },
                { timeout: 5000 }
            )
        })
    })

    describe('value labels overlay', () => {
        it('renders a value label per non-zero point when showValuesOnSeries is enabled', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showValuesOnSeries: true },
                }),
            })

            await waitFor(() => {
                const labels = getHogChart().valueLabels()
                expect(labels.length).toBeGreaterThan(0)
            })
            // Pageview series is [45, 82, 134, 210, 95]; all non-zero => 5 labels.
            const labels = getHogChart()
                .valueLabels()
                .map((l) => l.text)
            expect(labels).toContain('45')
            expect(labels).toContain('210')
        })

        it('formats value labels as percentages in percent stack view', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsAreaGraph,
                        showPercentStackView: true,
                        showValuesOnSeries: true,
                    },
                }),
            })

            await waitFor(() => {
                expect(getHogChart().valueLabels().length).toBeGreaterThan(0)
            })
            const labels = getHogChart().valueLabels()
            for (const l of labels) {
                expect(l.text).toMatch(/%/)
            }
        })
    })

    describe('log y-scale', () => {
        it('renders without crashing when series contain zero values', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                    trendsFilter: { yAxisScaleType: 'log10' },
                }),
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)
            expect(tooltip.row('ActiveSeries')).toContain('3')
            expect(tooltip.row('EmptySeries')).toContain('0')
        })
    })

    describe('confidence intervals overlay', () => {
        beforeEach(() => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showConfidenceIntervals: true, confidenceLevel: 95 },
                }),
            })
        })

        it('adds a CI band series when enabled', async () => {
            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })
        })
    })

    describe('trend lines overlay', () => {
        beforeEach(() => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { showTrendLines: true },
                }),
            })
        })

        it('omits the trend-line series from tooltip rows', async () => {
            const tooltip = await chart.hoverTooltip(2)

            expect(tooltip.row('Pageview')).toContain('134')
            // The trend-line carries the same series label; only the main
            // row should appear, so there must be exactly one row matching.
            const matching = tooltip.rows().filter((label) => label.includes('Pageview'))
            expect(matching).toHaveLength(1)
        })
    })

    describe('trend lines + moving average', () => {
        it('renders separate trend lines for the raw and moving-average series', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        showTrendLines: true,
                        showMovingAverage: true,
                        movingAverageIntervals: 3,
                    },
                }),
            })

            // main + raw trendline + moving avg + moving-avg trendline = 4 series.
            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 4 data series/i)).toBeInTheDocument()
            })
        })
    })

    describe('empty state', () => {
        it('renders InsightEmptyState when all series are zero', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
                }),
            })

            await waitFor(() => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            })
            expect(screen.queryByLabelText(/chart with/i)).not.toBeInTheDocument()
        })

        it('uses context.emptyStateHeading override when provided', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
                }),
                context: { emptyStateHeading: 'Nothing to see here, hedgehog' },
            })

            await waitFor(() => {
                expect(screen.getByText('Nothing to see here, hedgehog')).toBeInTheDocument()
            })
        })
    })

    describe('click → persons modal', () => {
        it('single series: direct click shows the actors for the clicked day', async () => {
            renderInsight({ query: buildTrendsQuery() })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['pageview-wed-a@example.com', 'pageview-wed-b@example.com'])
            })
            expect(personsModal.title()).toMatch(/12 Jun/)
        })

        it('multi-series: first click pins the tooltip without opening the modal', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await chart.clickAtIndex(2)

            expect(chart.getTooltip()).toBeInTheDocument()
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it('multi-series: clicking the Spike row shows only Spike actors', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await chart.clickAtIndex(2)
            await chart.clickTooltipRow('Spike')

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['spike-fan@example.com'])
            })
        })

        it('fires context.onDataPointClick instead of opening the persons modal', async () => {
            const onDataPointClick = jest.fn()
            renderInsight({
                query: buildTrendsQuery(),
                context: { onDataPointClick },
            })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(onDataPointClick).toHaveBeenCalledTimes(1)
            })
            const [seriesArg] = onDataPointClick.mock.calls[0]
            expect(seriesArg.day).toBe('2024-06-12')
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        describe('shared mode', () => {
            beforeEach(() => {
                // Shared/exported pages set this global before React mounts; trendsDataLogic.hasPersonsModal reads it.
                window.POSTHOG_EXPORTED_DATA = { type: ExportType.Embed }
            })

            afterEach(() => {
                delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
            })

            it('clicking a data point does not open the persons modal', async () => {
                renderInsight({ query: buildTrendsQuery(), inSharedMode: true })

                await chart.clickAtIndex(2)

                // Sharing-token auth can't run person-level queries, so shared views must not offer the drill-down.
                expect(personsModal.get()).not.toBeInTheDocument()
            })
        })
    })

    describe('quill in-chart legend (PRODUCT_ANALYTICS_QUILL_LEGEND on)', () => {
        const quillLegendFlag = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]: true }
        const twoSeriesQuery = buildTrendsQuery({
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            ],
            trendsFilter: { showLegend: true },
        })

        const getInChartLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-line-legend"]')!

        it('renders the in-chart legend and suppresses the legacy side legend', async () => {
            const { container } = renderInsight({ query: twoSeriesQuery, featureFlags: quillLegendFlag })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const legendEl = getInChartLegend(container)
            expect(legendEl.textContent).toContain('Napped')
            expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
        })

        it('keeps a toggled-off series listed and dimmed in the legend but out of the tooltip', async () => {
            const { container } = renderInsight({ query: twoSeriesQuery, featureFlags: quillLegendFlag })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })
            const legendEl = getInChartLegend(container)

            await legend.toggle('Napped')

            // Hidden series stays listed (so it can be restored) but is rendered dimmed.
            const nappedRow = await waitFor(() => {
                const row = [...legendEl.querySelectorAll<HTMLElement>('button')].find((b) =>
                    b.textContent?.includes('Napped')
                )
                expect(row?.className).toContain('opacity-40')
                return row
            })
            expect(nappedRow).toBeInTheDocument()

            const tooltip = await chart.hoverTooltip(2)
            expect(tooltip.element.textContent).not.toContain('Napped')
        })

        it('renders a static, non-interactive legend in shared mode', async () => {
            const { container } = renderInsight({
                query: twoSeriesQuery,
                featureFlags: quillLegendFlag,
                inSharedMode: true,
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })
            const legendEl = getInChartLegend(container)

            expect(legendEl.textContent).toContain('Napped')
            expect(legendEl.querySelector('button')).not.toBeInTheDocument()
        })
    })
})
