import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom, setupSyncRaf } from 'lib/hog-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildStickinessQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

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

const HOG_CHARTS_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_STICKINESS]: true }
const stickinessBar = (extra?: Parameters<typeof buildStickinessQuery>[0]): ReturnType<typeof buildStickinessQuery> =>
    buildStickinessQuery({ stickinessFilter: { display: ChartDisplayType.ActionsBar }, ...extra })

describe('StickinessBarChart', () => {
    it.each([
        { display: ChartDisplayType.ActionsBar, layout: 'stacked' },
        { display: ChartDisplayType.ActionsUnstackedBar, layout: 'grouped' },
    ])('renders a $layout bar chart from a StickinessQuery', async ({ display }) => {
        renderInsight({
            query: stickinessBar({ stickinessFilter: { display } }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByTestId('stickiness-bar-graph')).toBeInTheDocument()
        })
    })

    it('renders one series per event', async () => {
        renderInsight({
            query: stickinessBar({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with 2 data series/i })).toBeInTheDocument()
        })
    })

    it('y-axis: renders percent ticks (legacy `${value.toFixed(1)}%` parity)', async () => {
        renderInsight({ query: stickinessBar(), featureFlags: HOG_CHARTS_FLAG })

        await screen.findByRole('img', { name: /chart with/i })
        const ticks = getHogChart().yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        expect(ticks.every((t) => /%/.test(t))).toBe(true)
    })

    it('tooltip: percent value + "stickiness on {interval} {day}" title (not a calendar date)', async () => {
        renderInsight({ query: stickinessBar(), featureFlags: HOG_CHARTS_FLAG })

        const tooltip = await chart.hoverTooltip(2)
        // Days are 1-indexed in the mock, so bucket 2 == day 3.
        expect(tooltip.row('Pageview')).toMatch(/%/)
        expect(tooltip.title()).toMatch(/stickiness on day 3/i)
        // Must NOT default to a Unix-epoch-derived calendar date.
        expect(tooltip.title()).not.toMatch(/1970/i)
    })

    it('renders InsightEmptyState when all series are zero', async () => {
        renderInsight({
            query: stickinessBar({
                series: [{ kind: NodeKind.EventsNode, event: 'NoActivity', name: 'NoActivity' }],
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })

        await waitFor(() => {
            expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
        })
        expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
    })

    it('click → persons modal: opens with a "stickiness on {interval} {day}" title', async () => {
        renderInsight({ query: stickinessBar(), featureFlags: HOG_CHARTS_FLAG })

        await chart.clickAtIndex(2)

        await waitFor(() => {
            expect(personsModal.get()).toBeInTheDocument()
        })
        expect(personsModal.title()).toMatch(/stickiness on day 3/i)
        expect(personsModal.title()).toMatch(/Pageview/i)
    })

    it('click → context.onDataPointClick fires with the integer day instead of opening the modal', async () => {
        const onDataPointClick = jest.fn()
        renderInsight({
            query: stickinessBar(),
            context: { onDataPointClick },
            featureFlags: HOG_CHARTS_FLAG,
        })

        await chart.clickAtIndex(2)

        await waitFor(() => {
            expect(onDataPointClick).toHaveBeenCalledTimes(1)
        })
        const [seriesArg] = onDataPointClick.mock.calls[0]
        expect(seriesArg.day).toBe(3)
        expect(personsModal.get()).not.toBeInTheDocument()
    })
})
