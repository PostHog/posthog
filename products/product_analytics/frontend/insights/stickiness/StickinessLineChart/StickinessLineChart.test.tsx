import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom, setupSyncRaf } from 'lib/hog-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildStickinessQuery, chart, getHogChart, personsModal, renderInsight } from '~/test/insight-testing'

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

describe('StickinessLineChart', () => {
    describe('renders', () => {
        it('renders the chart from a StickinessQuery with one series', async () => {
            renderInsight({ query: buildStickinessQuery(), featureFlags: HOG_CHARTS_FLAG })

            await screen.findByRole('img', { name: /chart with 1 data series/i }, { timeout: 3000 })
        })
    })

    describe('y-axis', () => {
        it('renders percent ticks (legacy `${value.toFixed(1)}%` parity)', async () => {
            renderInsight({ query: buildStickinessQuery(), featureFlags: HOG_CHARTS_FLAG })

            await screen.findByRole('img', { name: /chart with/i })
            const ticks = getHogChart().yTicks()
            expect(ticks.length).toBeGreaterThan(0)
            for (const t of ticks) {
                expect(t).toMatch(/%/)
            }
        })
    })

    describe('tooltips', () => {
        it('formats series values as percentages of the series total', async () => {
            renderInsight({ query: buildStickinessQuery(), featureFlags: HOG_CHARTS_FLAG })

            const tooltip = await chart.hoverTooltip(2)
            // Pageview canned series is [45, 82, 134, 210, 95], total 566, so bucket 2 == 134/566 ≈ 23.7%.
            expect(tooltip.row('Pageview')).toMatch(/%/)
        })

        it('uses "stickiness on {interval} {day}" as the tooltip title (not a calendar date)', async () => {
            renderInsight({ query: buildStickinessQuery(), featureFlags: HOG_CHARTS_FLAG })

            const tooltip = await chart.hoverTooltip(2)
            // Day at index 2 is 3 in the mock's 1-indexed stickiness days.
            expect(tooltip.title()).toMatch(/stickiness on day 3/i)
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
                featureFlags: HOG_CHARTS_FLAG,
            })

            await waitFor(() => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            })
            expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
        })
    })

    describe('click → persons modal', () => {
        it('opens the modal with a "stickiness on {interval} {day}" title', async () => {
            renderInsight({ query: buildStickinessQuery(), featureFlags: HOG_CHARTS_FLAG })

            await chart.clickAtIndex(2)

            await waitFor(() => {
                expect(personsModal.get()).toBeInTheDocument()
            })
            // The clicked bucket is index 2, days are 1-indexed in the mock, so day == 3.
            expect(personsModal.title()).toMatch(/stickiness on day 3/i)
            expect(personsModal.title()).toMatch(/Pageview/i)
        })

        it('fires context.onDataPointClick with the integer day instead of opening the modal', async () => {
            const onDataPointClick = jest.fn()
            renderInsight({
                query: buildStickinessQuery(),
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
})
