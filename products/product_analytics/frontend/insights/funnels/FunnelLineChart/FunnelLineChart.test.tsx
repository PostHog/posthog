import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { dragSelection, ensureJsdom, waitForHogChartTooltip } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import {
    buildFunnelsQuery,
    chart,
    getHogChart,
    getQuerySource,
    personsModal,
    renderInsight,
} from '~/test/insight-testing'
import { buildAnnotation } from '~/test/insight-testing/test-data'
import { AnnotationScope } from '~/types'

import { FUNNEL_CONVERSION_SERIES_LABEL } from '../shared/funnelSeriesMeta'

configure({ asyncUtilTimeout: 3000 })

ensureJsdom()

afterEach(() => {
    personsModal.cleanupAll()
    cleanup()
})

describe('FunnelLineChart', () => {
    describe('series rendering', () => {
        it('renders a single conversion series with percentage values in the tooltip', async () => {
            renderInsight({ query: buildFunnelsQuery() })

            const tooltip = await chart.hoverTooltip(2)

            expect(getHogChart().seriesCount).toBe(1)
            expect(tooltip.element.textContent).toContain(FUNNEL_CONVERSION_SERIES_LABEL)
            expect(tooltip.element.textContent).toContain('40%')
        })

        it('renders a series per breakdown variant with the breakdown label on each tooltip row', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await waitFor(() => {
                expect(getHogChart().seriesCount).toBe(2)
            })

            await chart.clickAtIndex(2)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('Spike')
            expect(tooltip.textContent).toContain('Bramble')
        })

        it('shows each breakdown series conversion value, not a placeholder dash', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            // Every breakdown series is its own tooltip row and must render its own
            // conversion value. Regression guard: distinct series orders previously
            // split the rows across columns the inverted layout never rendered, so
            // only the first series showed a value and the rest showed "–".
            expect(tooltip.row('Spike')).toContain('50%')
            expect(tooltip.row('Bramble')).toContain('30%')
        })

        describe('orders breakdown rows by descending conversion value', () => {
            let orderedRows: { label: string; value: string | undefined }[]

            beforeAll(async () => {
                renderInsight({
                    query: buildFunnelsQuery({
                        breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' },
                    }),
                })

                const tooltip = await chart.hoverTooltip(2)
                orderedRows = tooltip.rows().map((label) => ({ label, value: tooltip.row(label) }))
            })

            // The query returns Safari, Chrome, Firefox, but at index 2 the conversion values are
            // Firefox=60%, Safari=40%, Chrome=20%, so rows must be re-ordered by descending value.
            it('sorts rows Firefox (60%), Safari (40%), Chrome (20%)', () => {
                expect(orderedRows).toEqual([
                    { label: expect.stringContaining('Firefox'), value: expect.stringContaining('60%') },
                    { label: expect.stringContaining('Safari'), value: expect.stringContaining('40%') },
                    { label: expect.stringContaining('Chrome'), value: expect.stringContaining('20%') },
                ])
            })
        })

        it('shows a distinct conversion value for each breakdown × compare series', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    compareFilter: { compare: true },
                }),
            })

            const tooltip = await chart.hoverTooltip(2)

            // Current and previous of the same breakdown are separate tooltip rows, keyed by
            // breakdown_value/compare_label. Regression guard: without compare_label threaded into
            // the tooltip datum, both rows collapsed into one shared column and only the current
            // value rendered, leaving the previous row showing "–".
            expect(tooltip.row('Spike · Current')).toContain('50%')
            expect(tooltip.row('Spike · Previous')).toContain('45%')
            expect(tooltip.row('Bramble · Current')).toContain('30%')
            expect(tooltip.row('Bramble · Previous')).toContain('25%')
        })
    })

    describe('click → persons modal', () => {
        it('opens the persons modal with the day-scoped actors for a single-series chart', async () => {
            renderInsight({ query: buildFunnelsQuery() })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['funnel-wed-a@example.com', 'funnel-wed-b@example.com'])
            })
            expect(personsModal.title()).toMatch(/12 Jun/)
        })

        it('opens the persons modal scoped to the clicked breakdown row', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            })

            await chart.clickAtIndex(2)
            await chart.clickTooltipRow('Spike')

            await waitFor(() => {
                expect(personsModal.actorNames()).toEqual(['funnel-spike@example.com'])
            })
        })
    })

    describe('value labels overlay', () => {
        it('renders percentage value labels when showValuesOnSeries is enabled', async () => {
            renderInsight({
                query: buildFunnelsQuery({ funnelsFilter: { showValuesOnSeries: true } }),
            })

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => {
                const texts = getHogChart()
                    .valueLabels()
                    .map((l) => l.text)
                // default fixture data [10, 25, 40, 60, 35] rendered as percentages
                expect([...texts].sort()).toEqual(['10%', '25%', '35%', '40%', '60%'])
            })
        })
    })

    describe('legend', () => {
        it('shows a legend item per breakdown series when showLegend is enabled', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    funnelsFilter: { showLegend: true },
                }),
            })

            await screen.findByLabelText(/chart with/i)
            const legend = await screen.findByTestId('hog-chart-timeseries-line-legend')
            const labels = Array.from(legend.children).map((el) => el.textContent?.trim())
            expect(labels).toEqual(['Spike', 'Bramble'])
        })

        it.each([
            {
                desc: 'showLegend is unset (off by default)',
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                }),
            },
            {
                desc: 'showLegend is false',
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    funnelsFilter: { showLegend: false },
                }),
            },
            {
                desc: 'there is only a single series, even when showLegend is true',
                query: buildFunnelsQuery({ funnelsFilter: { showLegend: true } }),
            },
        ])('omits the legend when $desc', async ({ query }) => {
            renderInsight({ query })

            await screen.findByLabelText(/chart with/i)
            expect(screen.queryByTestId('hog-chart-timeseries-line-legend')).not.toBeInTheDocument()
        })

        it('assigns a distinct color to each breakdown series', async () => {
            renderInsight({
                query: buildFunnelsQuery({
                    breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                    funnelsFilter: { showLegend: true },
                }),
            })

            await screen.findByLabelText(/chart with/i)
            const legend = await screen.findByTestId('hog-chart-timeseries-line-legend')
            // The label span also carries an inline style now (max-width), so keep only the colored swatches.
            const swatchColors = Array.from(legend.querySelectorAll<HTMLElement>('span[style]'))
                .map((el) => el.style.backgroundColor)
                .filter(Boolean)
            expect(swatchColors).toHaveLength(2)
            expect(new Set(swatchColors).size).toBe(2)
        })
    })

    describe('annotations', () => {
        it.each([
            { showAnnotations: undefined, expectsBadges: true },
            { showAnnotations: true, expectsBadges: true },
            { showAnnotations: false, expectsBadges: false },
        ])(
            'respects the showAnnotations funnels filter (showAnnotations=$showAnnotations)',
            async ({ showAnnotations, expectsBadges }) => {
                renderInsight({
                    query: buildFunnelsQuery({ funnelsFilter: { showAnnotations } }),
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

                if (expectsBadges) {
                    await waitFor(() => {
                        expect(document.querySelectorAll('.AnnotationsBadge').length).toBeGreaterThan(0)
                    })
                } else {
                    await screen.findByLabelText(/chart with/i)
                    expect(document.querySelectorAll('.AnnotationsBadge')).toHaveLength(0)
                }
            }
        )
    })

    describe('drag-to-zoom', () => {
        const zoomFlag = { [FEATURE_FLAGS.INSIGHT_DRAG_TO_ZOOM]: true }
        const totalLabels = 5 // funnelTrendsSteps.default has 5 days/labels

        it('reports the dragged range as day strings to context.onDateRangeZoom', async () => {
            const onDateRangeZoom = jest.fn()
            renderInsight({ query: buildFunnelsQuery(), context: { onDateRangeZoom }, featureFlags: zoomFlag })

            const canvas = await screen.findByLabelText(/chart with/i)
            dragSelection(canvas.parentElement!, 1, 3, totalLabels)

            await waitFor(() => {
                expect(onDateRangeZoom).toHaveBeenCalledWith('2024-06-11', '2024-06-13')
            })
        })

        it('ignores drags when the drag-to-zoom flag is off', async () => {
            const onDateRangeZoom = jest.fn()
            renderInsight({
                query: buildFunnelsQuery(),
                context: { onDateRangeZoom },
                featureFlags: { [FEATURE_FLAGS.INSIGHT_DRAG_TO_ZOOM]: false },
            })

            const canvas = await screen.findByLabelText(/chart with/i)
            dragSelection(canvas.parentElement!, 1, 3, totalLabels)

            // A regression dropping the flag gate would ship zoom to everyone.
            expect(onDateRangeZoom).not.toHaveBeenCalled()
            expect(getQuerySource().dateRange).toBeUndefined()
        })
    })
})
