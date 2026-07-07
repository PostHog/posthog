import '@testing-library/jest-dom'

import { cleanup, configure, screen } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { buildRetentionQuery, chart, renderInsight } from '~/test/insight-testing'

configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('RetentionLineChart', () => {
    it('renders one line per cohort with retention percentages derived from the canned counts', async () => {
        renderInsight({ query: buildRetentionQuery() })

        // Two canned cohorts (Jun 10 and Jun 11) become two chart series.
        await screen.findByLabelText(/chart with 2 data series/i)

        // Day 1 retention: Jun 10 cohort 60/100 → 60%, Jun 11 cohort 20/50 → 40%.
        const tooltip = await chart.hoverTooltip(1, 3)
        expect(tooltip.title()).toContain('Day 1')
        expect(tooltip.row('Mon, Jun 10')).toMatch(/\b60(\.0+)?%/)
        expect(tooltip.row('Tue, Jun 11')).toMatch(/\b40(\.0+)?%/)
    })

    it('recomputes percentages against the prior interval when retentionReference is "previous"', async () => {
        renderInsight({
            query: buildRetentionQuery({ retentionFilter: { retentionReference: 'previous' } }),
        })

        await screen.findByLabelText(/chart with 2 data series/i)

        // Day 2 vs Day 1: Jun 10 cohort 30/60 → 50%, Jun 11 cohort 5/20 → 25%
        // (vs 30% and 10% against the Day 0 baseline).
        const tooltip = await chart.hoverTooltip(2, 3)
        expect(tooltip.title()).toContain('Day 2')
        expect(tooltip.row('Mon, Jun 10')).toMatch(/\b50(\.0+)?%/)
        expect(tooltip.row('Tue, Jun 11')).toMatch(/\b25(\.0+)?%/)
    })

    it('clicking a pinned tooltip row opens the retention modal for that cohort', async () => {
        renderInsight({ query: buildRetentionQuery() })

        await screen.findByLabelText(/chart with 2 data series/i)

        // Multi-series pinnable chart: first click pins the tooltip, a row click drills down.
        await chart.clickAtIndex(1, 3)
        await chart.clickTooltipRow(/Tue, Jun 11/)

        expect(await screen.findByText('Tue, Jun 11 Cohort')).toBeInTheDocument()
    })
})
