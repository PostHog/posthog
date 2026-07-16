import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildStickinessQuery, chart, personsModal, renderInsight } from '~/test/insight-testing'
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
    ])('renders a $layout bar chart from a StickinessQuery with one series per event', async ({ display }) => {
        renderInsight({
            query: stickinessBar({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
                stickinessFilter: { display },
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('stickiness-bar-graph')).toBeInTheDocument()
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })

    it('tooltip: formats series values as percentages of the series total', async () => {
        renderInsight({ query: stickinessBar() })

        const tooltip = await chart.hoverTooltip(2)
        expect(tooltip.row('Pageview')).toMatch(/%/)
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
        expect(screen.queryByLabelText(/chart with/i)).not.toBeInTheDocument()
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
                expect(screen.getByLabelText(/chart with 2 data series/i)).toBeInTheDocument()
            })

            const legendEl = getInChartLegend(container)
            expect(legendEl.textContent).toContain('Pageview')
            expect(legendEl.textContent).not.toContain('$pageview')
            expect(legendEl.textContent).toContain('Napped')
        })
    })
})
