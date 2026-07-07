import '@testing-library/jest-dom'

import { cleanup, configure, screen } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { buildRetentionQuery, chart, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

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

const retentionBarQuery = (): ReturnType<typeof buildRetentionQuery> =>
    buildRetentionQuery({ retentionFilter: { display: ChartDisplayType.ActionsBar } })

describe('RetentionBarChart', () => {
    it('renders the bar variant for the ActionsBar display with the same derived percentages', async () => {
        renderInsight({ query: retentionBarQuery() })

        await screen.findByLabelText(/chart with 2 data series/i)

        // Grouped bars tooltip only the hovered band slot; the band-1 center lands on the
        // second cohort's bar: Jun 11 Day 1 retention is 20/50 → 40%.
        const tooltip = await chart.hoverTooltip(1, 3)
        expect(tooltip.title()).toContain('Day 1')
        expect(tooltip.row('Tue, Jun 11')).toMatch(/\b40(\.0+)?%/)
    })

    it('clicking a pinned tooltip row opens the retention modal for that cohort', async () => {
        renderInsight({ query: retentionBarQuery() })

        await screen.findByLabelText(/chart with 2 data series/i)

        // First click pins the tooltip (narrowed to the hovered Jun 11 bar), a row click drills down.
        await chart.clickAtIndex(1, 3)
        await chart.clickTooltipRow(/Tue, Jun 11/)

        expect(await screen.findByText('Tue, Jun 11 Cohort')).toBeInTheDocument()
    })
})
