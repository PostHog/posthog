import '@testing-library/jest-dom'

import { cleanup, waitFor } from '@testing-library/react'

import type { Series } from '@posthog/quill-charts'
import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { buildStickinessQuery, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import type { TrendsSeriesMeta } from '../../trends/shared/trendsSeriesMeta'

// Capture the series the component hands to the quill bar chart so we can assert the resolved
// colors end-to-end (indexedResults → getTrendsColor → dimming) without poking at the canvas.
const mockCapturedSeries: Series<TrendsSeriesMeta>[][] = []
jest.mock('@posthog/quill-charts', () => {
    const actual = jest.requireActual('@posthog/quill-charts')
    return {
        __esModule: true,
        ...actual,
        TimeSeriesBarChart: (props: { series: Series<TrendsSeriesMeta>[] }) => {
            mockCapturedSeries.push(props.series)
            return null
        },
    }
})

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    mockCapturedSeries.length = 0
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('StickinessBarChart compare-against-previous', () => {
    it('dims the previous-period series to 0.5 alpha while the current period keeps its full color', async () => {
        renderInsight({
            query: buildStickinessQuery({
                stickinessFilter: { display: ChartDisplayType.ActionsBar },
                compareFilter: { compare: true },
            }),
        })

        await waitFor(
            () => {
                const latest = mockCapturedSeries[mockCapturedSeries.length - 1] ?? []
                if (!latest.some((s) => s.meta?.compare_label === 'previous')) {
                    throw new Error('compare series not captured yet')
                }
            },
            { timeout: 5000 }
        )

        const series = mockCapturedSeries[mockCapturedSeries.length - 1]
        const previous = series.find((s) => s.meta?.compare_label === 'previous')
        const current = series.find((s) => s.meta?.compare_label === 'current')

        expect(previous).not.toBeUndefined()
        expect(current).not.toBeUndefined()
        // Previous period is dimmed via rgba(...) at half opacity; current keeps the opaque palette color.
        expect(previous!.color).toMatch(/^rgba\(.+,\s*0?\.5\)$/)
        expect(current!.color).not.toMatch(/^rgba\(/)
    })
})
