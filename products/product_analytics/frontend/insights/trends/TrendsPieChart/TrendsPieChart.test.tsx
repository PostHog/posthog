import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

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

function sliceLabels(): string[] {
    return Array.from(document.querySelectorAll('[data-attr="hog-chart-pie-slice-label"]')).map(
        (el) => el.textContent ?? ''
    )
}

// Napped × hedgehog fixture: Spike 11, Thistle 4, Bramble 2, Prickles 2, Conker 0.
// Conker drops out (0% < the 5% slice-label threshold); total of the rest is 19,
// so percent mode renders 11/19, 4/19, 2/19, 2/19.
const pieByHedgehog = (trendsFilter: Record<string, unknown> = {}): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({
        series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
        breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
        trendsFilter: { display: ChartDisplayType.ActionsPie, showValuesOnSeries: true, ...trendsFilter },
    })

describe('TrendsPieChart (ActionsPie)', () => {
    it.each([
        {
            name: 'shows raw slice values when percent stack view is off',
            query: pieByHedgehog(),
            expectedLabels: ['11', '4', '2', '2'],
        },
        {
            name: 'formats slice values as percentages in percent stack view',
            query: pieByHedgehog({ showPercentStackView: true }),
            expectedLabels: ['57.9%', '21.1%', '10.5%', '10.5%'],
        },
    ])('$name', async ({ query, expectedLabels }) => {
        renderInsight({ query })
        await screen.findByRole('img', { name: /pie chart with/i }, { timeout: 5000 })

        await waitFor(
            () => {
                expect(sliceLabels().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
        expect([...sliceLabels()].sort()).toEqual([...expectedLabels].sort())
    })
})
