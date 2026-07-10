import '@testing-library/jest-dom'

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'

import { dimensions, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { ExportType } from '~/exporter/types'
import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
import { AnnotationScope, ChartDisplayType } from '~/types'

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

const trendsBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({
        trendsFilter: { display: ChartDisplayType.ActionsBar },
        ...extra,
    })

describe('TrendsBarChart (ActionsBar)', () => {
    it.each([
        {
            name: 'one series for a single event',
            query: trendsBar(),
            expected: 1,
        },
        {
            name: 'one series per breakdown value',
            query: trendsBar({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'Napped',
                        name: 'Napped',
                    },
                ],
                breakdownFilter: {
                    breakdown: 'hedgehog',
                    breakdown_type: 'event',
                },
            }),
            expected: 5,
        },
    ])('renders $name', async ({ query, expected }) => {
        renderInsight({ query })

        await waitFor(
            () => {
                expect(screen.getByLabelText(new RegExp(`chart with ${expected} data series`, 'i'))).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })

    it('shows the series value and a date header in the tooltip on hover', async () => {
        renderInsight({ query: trendsBar() })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        const tooltip = await chart.hoverTooltip(2)
        expect(tooltip.row('Pageview')).toContain('134')
        expect(tooltip.title()).toMatch(/Jun/)
    })

    it('stacked tooltip shows each series own value, not the cumulative stack total', async () => {
        // $pageview=134 and Napped=5 at index 2. Napped stacks on top of $pageview, so its
        // cumulative top is 139 — the tooltip must report Napped's own 5, not the running total.
        renderInsight({
            query: trendsBar({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'Napped',
                        name: 'Napped',
                    },
                ],
            }),
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        const tooltip = await chart.hoverTooltip(2)

        expect(tooltip.row('Pageview')).toContain('134')
        expect(tooltip.row('Napped')).toContain('5')
        expect(tooltip.row('Napped')).not.toContain('139')
    })

    it('opens the persons modal on click for a single series', async () => {
        renderInsight({ query: trendsBar() })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        await chart.clickAtIndex(2)

        await waitFor(
            () => {
                expect(personsModal.actorNames()).toEqual(['pageview-wed-a@example.com', 'pageview-wed-b@example.com'])
            },
            { timeout: 5000 }
        )
        expect(personsModal.title()).toMatch(/12 Jun/)
    })

    describe('shared mode', () => {
        beforeEach(() => {
            // Shared/exported pages set this global before React mounts; trendsDataLogic.hasPersonsModal reads it.
            window.POSTHOG_EXPORTED_DATA = { type: ExportType.Embed }
        })

        afterEach(() => {
            delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
        })

        it('clicking a bar does not open the persons modal', async () => {
            renderInsight({ query: trendsBar(), inSharedMode: true })
            await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

            await chart.clickAtIndex(2)

            // Sharing-token auth can't run person-level queries, so shared views must not offer the drill-down.
            expect(personsModal.get()).not.toBeInTheDocument()
        })
    })

    it.each([ChartDisplayType.ActionsBar, ChartDisplayType.ActionsBarValue])(
        'renders InsightEmptyState when all values are zero for %s',
        async (display) => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: { display },
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'NoActivity',
                            name: 'NoActivity',
                        },
                    ],
                }),
            })

            await waitFor(
                () => {
                    expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
                },
                { timeout: 5000 }
            )
            expect(screen.queryByLabelText(/chart with/i)).not.toBeInTheDocument()
        }
    )

    it('shows current and previous period rows in compare mode', async () => {
        renderInsight({
            query: trendsBar({ compareFilter: { compare: true } }),
        })

        await waitFor(
            () => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )

        const tooltip = await chart.hoverTooltip(2)

        expect(tooltip.row('Current')).toBeTruthy()
        expect(tooltip.row('Previous')).toBeTruthy()
    })

    it('formats values as percentages in percent stack view', async () => {
        renderInsight({
            query: trendsBar({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'Napped',
                        name: 'Napped',
                    },
                ],
                trendsFilter: {
                    display: ChartDisplayType.ActionsBar,
                    showPercentStackView: true,
                },
            }),
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        const tooltip = await chart.hoverTooltip(2)

        expect(tooltip.row('Pageview')).toMatch(/%/)
    })
})

describe('TrendsBarChart (ActionsBarValue)', () => {
    const aggregatedBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
        buildTrendsQuery({
            trendsFilter: { display: ChartDisplayType.ActionsBarValue },
            ...extra,
        })

    it('renders custom axis titles in horizontal aggregated mode', async () => {
        renderInsight({
            query: aggregatedBar({
                trendsFilter: {
                    display: ChartDisplayType.ActionsBarValue,
                    xAxisLabel: 'Total events',
                    yAxisLabel: 'Series',
                },
            }),
        })

        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })
        expect(getHogChart().xAxisLabel()).toBe('Total events')
        expect(getHogChart().yAxisLabel()).toBe('Series')
        expect(
            getHogChart()
                .element.querySelector<SVGTextElement>('[data-attr="hog-chart-axis-title-y"]')
                ?.getAttribute('transform')
        ).toContain('rotate(-90')
    })

    // Five hedgehog breakdowns → by default one series carrying five per-bar colors across five
    // bands, labeled by breakdown value; with stackBreakdownValues they collapse onto one band.
    it.each([
        {
            name: 'one band per breakdown value, labeled by breakdown value, by default',
            stackBreakdownValues: undefined,
            expectedSeries: 1,
            expectedTicks: 5,
            containsTick: 'Spike',
        },
        {
            name: 'collapses breakdown bars onto one band when stackBreakdownValues is set',
            stackBreakdownValues: true,
            expectedSeries: 5,
            expectedTicks: 1,
            containsTick: undefined,
        },
    ])('$name', async ({ stackBreakdownValues, expectedSeries, expectedTicks, containsTick }) => {
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsBarValue, stackBreakdownValues },
            }),
        })
        await screen.findByLabelText(new RegExp(`chart with ${expectedSeries} data series`, 'i'), undefined, {
            timeout: 5000,
        })

        await waitFor(
            () => {
                const ticks = getHogChart().yTicks()
                expect(ticks).toHaveLength(expectedTicks)
                if (containsTick) {
                    expect(ticks).toEqual(expect.arrayContaining([containsTick]))
                }
            },
            { timeout: 5000 }
        )
    })

    it('colors each value-label pill by its own bar, not the first bar', async () => {
        // Regression: the single collapsed series carries per-bar colors, so value labels must
        // resolve `bars[dataIndex].color` — not the series-level color (which is just bars[0].color).
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsBarValue, showValuesOnSeries: true },
            }),
        })
        await screen.findByLabelText(/chart with 1 data series/i, undefined, { timeout: 5000 })

        await waitFor(
            () => {
                expect(getHogChart().valueLabels().length).toBeGreaterThan(1)
            },
            { timeout: 5000 }
        )
        const pillColors = getHogChart()
            .valueLabels()
            .map((l) => l.color)
        expect(new Set(pillColors).size).toBeGreaterThan(1)
    })

    // A dashboard/card tile is a fixed height, so the chart caps the breakdown rows to those that
    // fit. The full insight page is `embedded: false` — even when opened from a dashboard, where
    // `dashboardId` is in the URL — so it must keep growing to render every breakdown row.
    it.each([
        { name: 'insight page (not embedded) renders every breakdown bar', embedded: false, expectAllRows: true },
        {
            name: 'dashboard tile (embedded) caps bars to those that fit the tile',
            embedded: true,
            expectAllRows: false,
        },
    ])('$name', async ({ embedded, expectAllRows }) => {
        const totalRows = 20
        const manyBreakdowns = {
            results: Array.from({ length: totalRows }, (_, i) => ({
                action: { id: '$napped', type: 'events', name: 'Napped', order: 0 },
                label: `value ${i}`,
                count: totalRows - i,
                aggregated_value: totalRows - i,
                data: [totalRows - i],
                labels: ['Day 1'],
                days: ['2024-01-01'],
                breakdown_value: `value-${i}`,
            })),
        }
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
            }),
            embedded,
            mocks: {
                additionalMockResponses: [{ match: (q) => q.kind === NodeKind.TrendsQuery, response: manyBreakdowns }],
            },
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        await waitFor(
            () => {
                const ticks = getHogChart().yTicks()
                if (expectAllRows) {
                    expect(ticks).toHaveLength(totalRows)
                } else {
                    expect(ticks.length).toBeGreaterThan(0)
                    expect(ticks.length).toBeLessThan(totalRows)
                }
            },
            { timeout: 5000 }
        )
    })

    it('omits the header from the tooltip', async () => {
        renderInsight({
            query: aggregatedBar(),
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        const tooltip = await chart.hoverTooltip(0)
        expect(tooltip.title()).toBe('')
    })

    it('opens the persons modal on click without resolving a day', async () => {
        renderInsight({
            query: aggregatedBar(),
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        await chart.clickAtIndex(0)

        await waitFor(
            () => {
                expect(personsModal.get()).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        // Aggregated mode has no DateDisplay in the title.
        expect(personsModal.title()).not.toMatch(/Wednesday/)
    })

    it('fires context.onDataPointClick without a day argument', async () => {
        // Per-band breakdown resolution is covered at the unit-handler level — the
        // hog-charts hover/click helpers don't yet handle horizontal axis-orientation, so
        // integration coverage stays at the single-bar level here.
        const onDataPointClick = jest.fn()
        renderInsight({
            query: aggregatedBar(),
            context: { onDataPointClick },
        })
        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })

        await chart.clickAtIndex(0)

        await waitFor(
            () => {
                expect(onDataPointClick).toHaveBeenCalledTimes(1)
            },
            { timeout: 5000 }
        )
        const [seriesArg] = onDataPointClick.mock.calls[0]
        expect(seriesArg.day).toBeUndefined()
    })

    it('tooltip on a breakdown shows that breakdown row with its own value', async () => {
        // Regression: aggregated tooltip used to read the visible series's value at
        // ctx.dataIndex, a sparse-zero cell, so the row showed `0` (or the wrong row).
        renderInsight({
            query: aggregatedBar({
                series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
            }),
        })
        await screen.findByLabelText(/chart with 1 data series/i, undefined, { timeout: 5000 })

        // Spike has aggregated_value 11 — largest, so it's the topmost row in DESC layout.
        const canvas = screen.getByLabelText(/chart with/i)
        const wrapper = canvas.parentElement!
        fireEvent.mouseMove(wrapper, {
            clientX: dimensions.plotLeft + 10,
            clientY: dimensions.plotTop + 10,
        })

        const tooltip = chart.getTooltip()
        expect(tooltip).not.toBeNull()
        const rowText = tooltip!.textContent ?? ''
        expect(rowText).toContain('Spike')
        expect(rowText).toContain('11')
    })

    it('keeps the previous-period identifier glyph opaque while dimming only the row ribbon', async () => {
        // Give the previous period the larger aggregated_value so it sorts topmost (DESC) and is the
        // bar hovered at plotTop. Its series color arrives pre-dimmed (rgba .5); the ribbon should keep
        // that dim to mark the period, but the SeriesLetter glyph must render at full opacity.
        const action = { id: '$pageview', type: 'events', name: '$pageview', order: 0 }
        const compareResults = {
            results: [
                {
                    action,
                    label: '$pageview',
                    count: 50,
                    aggregated_value: 50,
                    data: [50],
                    labels: ['Day 1'],
                    days: ['2024-06-10'],
                    compare: true,
                    compare_label: 'current',
                },
                {
                    action,
                    label: '$pageview',
                    count: 500,
                    aggregated_value: 500,
                    data: [500],
                    labels: ['Day 1'],
                    days: ['2024-06-03'],
                    compare: true,
                    compare_label: 'previous',
                },
            ],
        }
        renderInsight({
            query: aggregatedBar({ compareFilter: { compare: true } }),
            // Pin to the legacy InsightTooltip path — the glyph/ribbon assertions are specific
            // to that rendering and will get a quill-flavoured equivalent when the flag ships.
            featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]: false },
            mocks: {
                additionalMockResponses: [{ match: (q) => q.kind === NodeKind.TrendsQuery, response: compareResults }],
            },
        })
        const canvas = await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })
        const wrapper = canvas.parentElement!
        // Topmost band is the previous period (largest aggregated_value, sorted DESC). Aim at the
        // band centre — the bar's hittable region sits inside the band's padding.
        const previousBandY = dimensions.plotTop + dimensions.plotHeight / 4

        // Re-fire the hover each tick until the chart commits its scales and the tooltip populates —
        // a single mouseMove before the chart settles is silently dropped.
        await waitFor(
            () => {
                fireEvent.mouseMove(wrapper, { clientX: dimensions.plotLeft + 30, clientY: previousBandY })
                const glyph = chart.getTooltip()?.querySelector<HTMLElement>('.graph-series-glyph')
                expect(glyph).toBeTruthy()
                // The identifier glyph stays opaque — no alpha channel bled in from the dimmed color.
                expect(glyph!.style.color).not.toMatch(/rgba/)
                expect(glyph!.style.borderColor).not.toMatch(/rgba/)
                // The left ribbon still carries the half-opacity previous-period color.
                const ribbon = glyph!.closest('tr')!.style.getPropertyValue('--row-ribbon-color')
                expect(ribbon).toMatch(/rgba\([^)]*0?\.5\)/)
            },
            { timeout: 8000 }
        )
    }, 12000)
})

describe('TrendsBarChart (ActionsUnstackedBar)', () => {
    const groupedBar = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
        buildTrendsQuery({
            trendsFilter: { display: ChartDisplayType.ActionsUnstackedBar },
            ...extra,
        })

    it('renders one band per series in grouped layout', async () => {
        renderInsight({
            query: groupedBar({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'Napped',
                        name: 'Napped',
                    },
                ],
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })
})

describe('TrendsBarChart overlays', () => {
    it('renders value labels when showValuesOnSeries is enabled', async () => {
        renderInsight({
            query: buildTrendsQuery({
                trendsFilter: {
                    display: ChartDisplayType.ActionsBar,
                    showValuesOnSeries: true,
                },
            }),
        })

        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })
        await waitFor(
            () => {
                expect(getHogChart().valueLabels().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
        const labels = getHogChart()
            .valueLabels()
            .map((l) => l.text)
        // Pageview series peaks at 210 — it should appear among the rendered labels.
        expect(labels).toContain('210')
    })

    it('renders an annotation badge when an annotation exists', async () => {
        renderInsight({
            query: buildTrendsQuery({
                trendsFilter: { display: ChartDisplayType.ActionsBar },
            }),
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

        await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })
        await waitFor(
            () => {
                expect(getHogChart().annotationBadges().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
    })

    // For ActionsBarValue (horizontal aggregated), axisOrientation='horizontal' flips the
    // line geometry to a vertical stripe at the value-axis x-pixel.
    it.each<{
        display: ChartDisplayType
        value: number
        expectedOrientation: 'horizontal' | 'vertical'
    }>([
        {
            display: ChartDisplayType.ActionsBar,
            value: 150,
            expectedOrientation: 'horizontal',
        },
        {
            display: ChartDisplayType.ActionsBarValue,
            value: 100,
            expectedOrientation: 'vertical',
        },
    ])(
        'renders a goal line with $expectedOrientation orientation for $display',
        async ({ display, value, expectedOrientation }) => {
            renderInsight({
                query: buildTrendsQuery({
                    trendsFilter: {
                        display,
                        goalLines: [{ label: 'Target', value, displayIfCrossed: true }],
                    },
                }),
            })

            await screen.findByLabelText(/chart with/i, undefined, { timeout: 5000 })
            await waitFor(
                () => {
                    const lines = getHogChart().referenceLines()
                    expect(lines.map((l) => l.label)).toEqual(['Target'])
                    expect(lines[0].orientation).toBe(expectedOrientation)
                },
                { timeout: 5000 }
            )
        }
    )

    describe('quill in-chart legend (PRODUCT_ANALYTICS_QUILL_LEGEND on)', () => {
        const quillLegendFlag = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]: true }
        const twoSeriesBar = trendsBar({
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            ],
            trendsFilter: { display: ChartDisplayType.ActionsBar, showLegend: true },
        })

        const getInChartLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-bar-legend"]')!

        it('renders the in-chart legend with a row per series', async () => {
            const { container } = renderInsight({ query: twoSeriesBar, featureFlags: quillLegendFlag })

            await waitFor(() => {
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const legendEl = getInChartLegend(container)
            expect(legendEl.textContent).toContain('Pageview')
            expect(legendEl.textContent).toContain('Napped')
        })
    })
})
