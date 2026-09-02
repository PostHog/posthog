import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { dimensions, dragSelection, rawDrag, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import type { IndexedTrendResult } from 'scenes/trends/types'
import { urls } from 'scenes/urls'

import { ExportType } from '~/exporter/types'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    buildTrendsQuery,
    chart,
    createInsightTooltipAccessor,
    getHogChart,
    getQuerySource,
    legend,
    personsModal,
    renderInsight,
    trendsSeries,
} from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
import { AnnotationScope, ChartDisplayType, InsightShortId } from '~/types'

import { extendLabelsToLongestSeries } from './TrendsLineChart'

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
    // featureFlagLogic persists flags to localStorage, so per-test flags leak into later tests otherwise
    localStorage.clear()
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

        it('prefixes rows with the series name when multiple series share a breakdown', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await chart.clickAtIndex(2)

            // Each breakdown value appears once per series; without the prefix the rows
            // would be indistinguishable (e.g. two bare "Spike" rows).
            const tooltip = createInsightTooltipAccessor(chart.getTooltip()!)
            expect(tooltip.row('Pageview · Spike')).toContain('90')
            expect(tooltip.row('Napped · Spike')).toContain('3')
        })

        it('adds series letters when same-named series share a breakdown', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                        { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                    ],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await chart.clickAtIndex(2)

            // The name alone can't tell the two series apart, so rows get the A/B
            // letters from the insight editor.
            const tooltip = createInsightTooltipAccessor(chart.getTooltip()!)
            const spikeRows = tooltip.rows().filter((label) => label.includes('Spike'))
            expect(spikeRows.map((label) => label[0]).sort()).toEqual(['A', 'B'])
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

        it('prefixes rows with the formula name when multiple formulas share a breakdown', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    trendsFilter: { formulas: ['A', 'A*2'] },
                }),
            })

            await chart.clickAtIndex(2)

            // Formula rows carry no `action`; their `order` is what keeps the repeated
            // breakdown values from separate formulas attributable.
            const tooltip = createInsightTooltipAccessor(chart.getTooltip()!)
            expect(tooltip.row('Formula (A) · Spike')).toContain('3')
            expect(tooltip.row('Formula (A*2) · Spike')).toContain('6')
        })

        it('dates the previous period row in compare mode', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    compareFilter: { compare: true },
                }),
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const tooltip = await chart.hoverTooltip(2)

            // Index 2 is 12 Jun in the current period, so 5 Jun can only come from the previous one.
            expect(tooltip.row('Current')).toContain('134')
            expect(tooltip.row('5 Jun')).toContain('100')
            expect(tooltip.element.textContent).not.toContain('Previous')
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
            // Axis titles are a layout-dependent overlay that commits a tick after the
            // chart's aria-label appears (like referenceLines/valueLabels below), so read
            // them through waitFor rather than synchronously.
            await waitFor(() => {
                expect(getHogChart().xAxisLabel()).toBe('Signup date')
                expect(getHogChart().yAxisLabel()).toBe('Unique users')
            })
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

        it('renders the chart when the first series is empty but a later one has data', async () => {
            // Regresses the bug this PR fixes: the old check only looked at
            // indexedResults[0], so a leading empty series blanked the whole chart even when a
            // later series (here, ActiveSeries) had real counts.
            renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'ZeroCounts', name: 'ZeroCounts' }],
                }),
            })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with/i)).toBeInTheDocument()
            })
            expect(screen.queryByTestId('insight-empty-state')).not.toBeInTheDocument()
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

    describe('display fallback', () => {
        it('renders the line chart for display types without a trends renderer', async () => {
            // `Auto` is schema-valid on a trends query (reachable via the API/MCP) but has no
            // dedicated branch in the trends render dispatch — it must not blank the tile.
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { display: ChartDisplayType.Auto },
                }),
            })

            await waitFor(() => {
                expect(screen.getByTestId('trend-line-graph')).toBeInTheDocument()
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
            // The pin outlives the click unless the drill-down drops it, leaving the tooltip over the modal.
            expect(chart.getTooltip()).not.toBeInTheDocument()
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

    describe('formula insights with drill-down disabled', () => {
        const multiSeriesFormulaQuery = buildTrendsQuery({
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            ],
            trendsFilter: { formula: 'A/B' },
        })

        /** Mirrors how InsightCard hands a dashboard tile's real short_id and query down through
         *  `context.insightProps.cachedInsight` (see InsightCard.tsx / InsightMeta.tsx). */
        const dashboardTileContext = (shortId: InsightShortId): QueryContext<InsightVizNode> => ({
            insightProps: {
                dashboardItemId: shortId,
                dashboardId: 42,
                cachedInsight: {
                    short_id: shortId,
                    query: { kind: NodeKind.InsightVizNode, source: multiSeriesFormulaQuery } as InsightVizNode,
                },
            },
        })

        it('offers no click affordance and does not open the persons modal', async () => {
            renderInsight({ query: multiSeriesFormulaQuery })

            await chart.hoverTooltip(2)

            expect(chart.getTooltip()?.textContent).not.toContain('Click to view')
            await chart.clickTooltipRow('Pageview')
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it('navigates to the insight on click when rendered as a dashboard/card tile', async () => {
            const shortId = 'formula-insight-1' as InsightShortId
            renderInsight({
                query: multiSeriesFormulaQuery,
                embedded: true,
                context: dashboardTileContext(shortId),
            })

            await chart.hoverTooltip(2)
            expect(chart.getTooltip()?.textContent).toContain('Click to view the insight')

            await chart.clickTooltipRow('Pageview')

            await waitFor(() => {
                const path = removeProjectIdIfPresent(router.values.location.pathname) + router.values.location.search
                expect(path).toEqual(urls.insightView(shortId, 42))
            })
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it('does not navigate on click when rendered in shared mode', async () => {
            const shortId = 'formula-insight-2' as InsightShortId
            renderInsight({
                query: multiSeriesFormulaQuery,
                embedded: true,
                inSharedMode: true,
                context: dashboardTileContext(shortId),
            })
            const pathnameBeforeClick = router.values.location.pathname

            await chart.hoverTooltip(2)
            await chart.clickTooltipRow('Pageview')

            expect(router.values.location.pathname).toEqual(pathnameBeforeClick)
        })
    })

    describe('quill in-chart legend', () => {
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
            const { container } = renderInsight({ query: twoSeriesQuery })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const legendEl = getInChartLegend(container)
            expect(legendEl.textContent).toContain('Napped')
            expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
        })

        it('keeps a toggled-off series listed and dimmed in the legend but out of the tooltip', async () => {
            const { container } = renderInsight({ query: twoSeriesQuery })

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

    describe('multi-year weekly x-axis', () => {
        // Week display labels omit the year ("1–7 Jun"), so a multi-year range repeats them.
        // The chart keys x positions off its labels prop and collapses a repeated key onto the
        // first occurrence's x, which draws the series backwards — so the components must key
        // the axis by the unique ISO days instead. Covers the bar path too, where a repeated
        // key collapses whole bands.
        it.each([
            ['line', undefined],
            ['bar', ChartDisplayType.ActionsBar],
        ])(
            'renders %s points at strictly increasing x when display labels repeat across years',
            async (_displayName, display) => {
                renderInsight({
                    query: buildTrendsQuery({
                        interval: 'week',
                        series: [{ kind: NodeKind.EventsNode, event: 'WeeklyAcrossYears', name: 'WeeklyAcrossYears' }],
                        trendsFilter: { showValuesOnSeries: true, ...(display ? { display } : {}) },
                    }),
                })

                await waitFor(() => {
                    expect(getHogChart().valueLabels()).toHaveLength(6)
                })
                const leftByText = new Map(
                    Array.from(document.querySelectorAll<HTMLElement>('[data-attr="hog-chart-value-label"]')).map(
                        (el) => [el.textContent, parseFloat(el.style.left)]
                    )
                )
                const lefts = ['10', '20', '30', '40', '50', '60'].map((text) => leftByText.get(text)!)
                for (let i = 1; i < lefts.length; i++) {
                    expect(lefts[i]).toBeGreaterThan(lefts[i - 1])
                }
            }
        )
    })

    describe('drag-to-zoom', () => {
        const totalLabels = trendsSeries.pageviews.labels.length
        const zoomFlag = { [FEATURE_FLAGS.INSIGHT_DRAG_TO_ZOOM]: true }

        async function getChartWrapper(): Promise<HTMLElement> {
            const canvas = await screen.findByLabelText(/chart with/i)
            return canvas.parentElement!
        }

        it('reports the dragged range as day strings to context.onDateRangeZoom', async () => {
            const onDateRangeZoom = jest.fn()
            renderInsight({ query: buildTrendsQuery(), context: { onDateRangeZoom }, featureFlags: zoomFlag })
            const wrapper = await getChartWrapper()

            dragSelection(wrapper, 1, 3, totalLabels)

            await waitFor(() => {
                // Days, not the formatted axis labels ('Tue'/'Thu') the chart renders with.
                expect(onDateRangeZoom).toHaveBeenCalledWith('2024-06-11', '2024-06-13')
            })
        })

        it('reports a drag that stays within a single bucket as that bucket', async () => {
            const onDateRangeZoom = jest.fn()
            renderInsight({ query: buildTrendsQuery(), context: { onDateRangeZoom }, featureFlags: zoomFlag })
            const wrapper = await getChartWrapper()

            // Both drag edges snap to the same label — the common case on sparse charts
            // (e.g. a 3-bar monthly chart), where this used to be a silent no-op.
            const step = dimensions.plotWidth / (totalLabels - 1)
            const x = dimensions.plotLeft + step
            const y = dimensions.plotTop + dimensions.plotHeight / 2
            rawDrag(wrapper, { from: { x: x - 40, y }, to: { x: x + 40, y } })

            await waitFor(() => {
                expect(onDateRangeZoom).toHaveBeenCalledWith('2024-06-11', '2024-06-11')
            })
        })

        it('ignores drags when the drag-to-zoom flag is off', async () => {
            const onDateRangeZoom = jest.fn()
            renderInsight({ query: buildTrendsQuery(), context: { onDateRangeZoom } })
            const wrapper = await getChartWrapper()

            dragSelection(wrapper, 1, 3, totalLabels)

            // A regression dropping the flag gate would ship zoom to everyone.
            expect(onDateRangeZoom).not.toHaveBeenCalled()
        })

        it('ignores drags when no context handler opts in', async () => {
            renderInsight({ query: buildTrendsQuery(), featureFlags: zoomFlag })
            const wrapper = await getChartWrapper()

            dragSelection(wrapper, 1, 3, totalLabels)

            expect(getQuerySource().dateRange).toBeUndefined()
        })
    })

    describe('extendLabelsToLongestSeries', () => {
        const result = (data: number[]): IndexedTrendResult => ({ data }) as IndexedTrendResult

        it('extends the hourly domain forward to a longer previous series', () => {
            const currentDays = ['2020-01-02 00:00:00', '2020-01-02 01:00:00', '2020-01-02 02:00:00']
            const extended = extendLabelsToLongestSeries(currentDays, 'hour', [
                result([0, 0, 1]),
                result([3, 0, 0, 0, 0]),
            ])
            expect(extended).toEqual([
                '2020-01-02 00:00:00',
                '2020-01-02 01:00:00',
                '2020-01-02 02:00:00',
                '2020-01-02 03:00:00',
                '2020-01-02 04:00:00',
            ])
        })

        it('leaves the domain untouched when no series is longer', () => {
            const days = ['2020-01-02', '2020-01-03', '2020-01-04']
            expect(extendLabelsToLongestSeries(days, 'day', [result([1, 2, 3]), result([4, 5, 6])])).toBe(days)
        })
    })
})
