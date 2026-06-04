import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, personsModal, renderInsight } from '~/test/insight-testing'
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

const HOG_CHARTS_FLAG = {
    [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_TRENDS]: true,
}

function sliceLabels(): string[] {
    return Array.from(document.querySelectorAll('[data-attr="hog-chart-pie-slice-label"]')).map(
        (el) => el.textContent ?? ''
    )
}

// Napped broken down by hedgehog yields per-slice aggregated values
// Spike 11, Thistle 4, Bramble 2, Prickles 2, Conker 0 (total 19).
const pieByHedgehog = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({
        series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
        breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
        trendsFilter: { display: ChartDisplayType.ActionsPie, showValuesOnSeries: true },
        ...extra,
    })

describe('TrendsPieChart (ActionsPie)', () => {
    it('shows raw slice values when percent stack view is off', async () => {
        renderInsight({ query: pieByHedgehog(), featureFlags: HOG_CHARTS_FLAG })
        await screen.findByRole('img', { name: /pie chart with/i }, { timeout: 5000 })

        await waitFor(
            () => {
                expect(sliceLabels().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
        const labels = sliceLabels()
        expect(labels).toContain('11') // Spike's aggregated value
        expect(labels.some((l) => l.includes('%'))).toBe(false)
    })

    it('formats slice values as percentages in percent stack view', async () => {
        renderInsight({
            query: pieByHedgehog({
                trendsFilter: {
                    display: ChartDisplayType.ActionsPie,
                    showValuesOnSeries: true,
                    showPercentStackView: true,
                },
            }),
            featureFlags: HOG_CHARTS_FLAG,
        })
        await screen.findByRole('img', { name: /pie chart with/i }, { timeout: 5000 })

        await waitFor(
            () => {
                expect(sliceLabels().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
        const labels = sliceLabels()
        // Spike is 11/19 ≈ 57.9% of the visible total.
        expect(labels).toContain('57.9%')
        expect(labels.every((l) => l.includes('%'))).toBe(true)
    })
})
