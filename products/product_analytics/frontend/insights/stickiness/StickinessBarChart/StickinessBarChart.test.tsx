import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildStickinessQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

configure({ asyncUtilTimeout: 3000 })

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

const stickinessBar = (extra?: Parameters<typeof buildStickinessQuery>[0]): ReturnType<typeof buildStickinessQuery> =>
    buildStickinessQuery({ stickinessFilter: { display: ChartDisplayType.ActionsBar }, ...extra })

describe('StickinessBarChart', () => {
    it.each([
        { display: ChartDisplayType.ActionsBar, layout: 'stacked' },
        { display: ChartDisplayType.ActionsUnstackedBar, layout: 'grouped' },
    ])('renders a $layout bar chart from a StickinessQuery', async ({ display }) => {
        renderInsight({
            query: stickinessBar({ stickinessFilter: { display } }),
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('stickiness-bar-graph')).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })

    it('renders one series per event', async () => {
        renderInsight({
            query: stickinessBar({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })

    it('y-axis: renders percent ticks (legacy `${value.toFixed(1)}%` parity)', async () => {
        renderInsight({ query: stickinessBar() })

        await screen.findByRole('img', { name: /chart with/i })
        await waitFor(() => {
            const ticks = getHogChart().yTicks()
            expect(ticks.length).toBeGreaterThan(0)
            expect(ticks.every((t) => /%/.test(t))).toBe(true)
        })
    })

    it('tooltip: percent value + "Stickiness on {interval} {day}" title (not a calendar date)', async () => {
        renderInsight({ query: stickinessBar() })

        const tooltip = await chart.hoverTooltip(2)
        // Days are 1-indexed in the mock, so bucket 2 == day 3.
        expect(tooltip.row('Pageview')).toMatch(/%/)
        expect(tooltip.title()).toMatch(/Stickiness on day 3/)
        // Must NOT default to a Unix-epoch-derived calendar date.
        expect(tooltip.title()).not.toMatch(/1970/i)
    })

    it('renders InsightEmptyState when all series are zero', async () => {
        renderInsight({
            query: stickinessBar({
                series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
    })

    it('click → persons modal: opens with a "stickiness on {interval} {day}" title', async () => {
        renderInsight({ query: stickinessBar() })

        await chart.clickAtIndex(2)

        await waitFor(
            () => {
                expect(personsModal.get()).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        expect(personsModal.title()).toMatch(/stickiness on day 3/)
        // Case-sensitive: the core event must be humanized ("Pageview"), not the raw "$pageview".
        expect(personsModal.title()).toMatch(/Pageview/)
    })

    it('click → context.onDataPointClick fires with the integer day instead of opening the modal', async () => {
        const onDataPointClick = jest.fn()
        renderInsight({
            query: stickinessBar(),
            context: { onDataPointClick },
        })

        await chart.clickAtIndex(2)

        await waitFor(
            () => {
                expect(onDataPointClick).toHaveBeenCalledTimes(1)
            },
            { timeout: 5000 }
        )
        const [seriesArg] = onDataPointClick.mock.calls[0]
        expect(seriesArg.day).toBe(3)
        expect(personsModal.get()).not.toBeInTheDocument()
    })

    describe('quill in-chart legend (PRODUCT_ANALYTICS_QUILL_LEGEND on)', () => {
        const quillLegendFlag = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]: true }
        const twoSeriesBar = stickinessBar({
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            ],
            stickinessFilter: { display: ChartDisplayType.ActionsBar, showLegend: true },
        })

        const getInChartLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-bar-legend"]')!

        it('humanizes core event names in the legend, leaving custom events as-is', async () => {
            const { container } = renderInsight({ query: twoSeriesBar, featureFlags: quillLegendFlag })

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
