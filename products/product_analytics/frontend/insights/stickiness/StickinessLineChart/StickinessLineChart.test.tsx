import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { ExportType } from '~/exporter/types'
import { NodeKind } from '~/queries/schema/schema-general'
import { buildStickinessQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'

configure({ asyncUtilTimeout: 5000 })
// With asyncUtilTimeout at 5s, a single legitimate waitFor can exhaust Jest's default
// 5s per-test budget on a contended CI shard.
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

describe('StickinessLineChart', () => {
    describe('renders', () => {
        it('renders the chart from a StickinessQuery with one series', async () => {
            renderInsight({ query: buildStickinessQuery() })

            await screen.findByRole('img', { name: /chart with 1 data series/i })
        })
    })

    describe('y-axis', () => {
        it('renders percent ticks (legacy `${value.toFixed(1)}%` parity)', async () => {
            renderInsight({ query: buildStickinessQuery() })

            await screen.findByRole('img', { name: /chart with/i })
            await waitFor(() => {
                const ticks = getHogChart().yTicks()
                expect(ticks.length).toBeGreaterThan(0)
                for (const t of ticks) {
                    expect(t).toMatch(/%/)
                }
            })
        })
    })

    describe('tooltips', () => {
        it('formats series values as percentages of the series total', async () => {
            renderInsight({ query: buildStickinessQuery() })

            const tooltip = await chart.hoverTooltip(2)
            // Pageview canned series is [45, 82, 134, 210, 95], total 566, so bucket 2 == 134/566 ≈ 23.7%.
            expect(tooltip.row('Pageview')).toMatch(/%/)
        })

        it('uses "Stickiness on {interval} {day}" as the tooltip title (not a calendar date)', async () => {
            renderInsight({ query: buildStickinessQuery() })

            const tooltip = await chart.hoverTooltip(2)
            // Day at index 2 is 3 in the mock's 1-indexed stickiness days.
            expect(tooltip.title()).toMatch(/Stickiness on day 3/)
            // Critically — must NOT default to a Unix-epoch-derived calendar date.
            expect(tooltip.title()).not.toMatch(/1970/i)
        })
    })

    describe('empty state', () => {
        it('renders InsightEmptyState when all series are zero', async () => {
            renderInsight({
                query: buildStickinessQuery({
                    series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
                }),
            })

            await waitFor(() => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            })
            expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
        })
    })

    describe('click → persons modal', () => {
        it('opens the modal with a "stickiness on {interval} {day}" title', async () => {
            renderInsight({ query: buildStickinessQuery() })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.get()).toBeInTheDocument()
            })
            // The clicked bucket is index 2, days are 1-indexed in the mock, so day == 3.
            expect(personsModal.title()).toMatch(/stickiness on day 3/)
            // Case-sensitive: the core event must be humanized ("Pageview"), not the raw "$pageview".
            expect(personsModal.title()).toMatch(/Pageview/)
        })

        it('fires context.onDataPointClick with the integer day instead of opening the modal', async () => {
            const onDataPointClick = jest.fn()
            renderInsight({
                query: buildStickinessQuery(),
                context: { onDataPointClick },
            })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(onDataPointClick).toHaveBeenCalledTimes(1)
            })
            const [seriesArg] = onDataPointClick.mock.calls[0]
            expect(seriesArg.day).toBe(3)
            expect(personsModal.get()).not.toBeInTheDocument()
        })

        it('shared mode: clicking a data point does not open the persons modal', async () => {
            // Shared/exported pages set this global before React mounts; trendsDataLogic.hasPersonsModal reads it.
            window.POSTHOG_EXPORTED_DATA = { type: ExportType.Embed }
            try {
                renderInsight({ query: buildStickinessQuery(), inSharedMode: true })

                await chart.clickAtIndex(2)

                // Sharing-token auth can't run person-level queries, so shared views must not offer the drill-down.
                expect(personsModal.get()).not.toBeInTheDocument()
            } finally {
                delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
            }
        })
    })

    describe('quill in-chart legend (PRODUCT_ANALYTICS_QUILL_LEGEND on)', () => {
        const quillLegendFlag = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]: true }
        const twoSeriesLine = buildStickinessQuery({
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            ],
            stickinessFilter: { showLegend: true },
        })

        const getInChartLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-line-legend"]')!

        it('humanizes core event names in the legend, leaving custom events as-is', async () => {
            const { container } = renderInsight({ query: twoSeriesLine, featureFlags: quillLegendFlag })

            await waitFor(() => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            })

            const legendEl = getInChartLegend(container)
            expect(legendEl.textContent).toContain('Pageview')
            expect(legendEl.textContent).not.toContain('$pageview')
            expect(legendEl.textContent).toContain('Napped')
        })
    })
})
