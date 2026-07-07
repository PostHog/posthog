import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor } from '@testing-library/react'

import { setupJsdom } from '@posthog/quill-charts/testing'

import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    buildActorsResponse,
    buildFunnelsQuery,
    chart,
    type MockResponse,
    personsModal,
    renderInsight,
} from '~/test/insight-testing'
import { FunnelVizType } from '~/types'

configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void

// No setupSyncRaf here: the bars' hover-fade animation re-requests a frame until time advances,
// so a synchronous RAF mock recurses until the stack overflows and crashes the chart on hover.
beforeEach(() => {
    cleanupJsdom = setupJsdom()
})

afterEach(() => {
    personsModal.cleanupAll()
    cleanupJsdom()
    cleanup()
})

interface StepsActorsSource {
    kind?: string
    funnelStep?: number
    funnelStepBreakdown?: unknown
}

// The harness's default funnel actors mock keys off funnelTrendsEntrancePeriodStart; steps-viz
// actor queries carry funnelStep/funnelStepBreakdown instead, so echo those into the actor email
// to prove the click scoped the query correctly.
const stepsFunnelActorsEcho: MockResponse = {
    match: (query) => {
        const source = (query as { source?: StepsActorsSource }).source
        return (
            query.kind === NodeKind.ActorsQuery &&
            source?.kind === NodeKind.FunnelsActorsQuery &&
            source.funnelStep != null
        )
    },
    response: (query) => {
        const source = (query as { source?: StepsActorsSource }).source!
        const breakdown = Array.isArray(source.funnelStepBreakdown)
            ? source.funnelStepBreakdown.join('+')
            : source.funnelStepBreakdown
        return buildActorsResponse([
            { email: `step${source.funnelStep}${breakdown == null ? '' : `-${breakdown}`}@example.com` },
        ])
    },
}

function stepsFunnelQuery(overrides: Partial<FunnelsQuery> = {}): FunnelsQuery {
    return buildFunnelsQuery({
        series: [
            { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
            { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            { kind: NodeKind.EventsNode, event: 'Snored', name: 'Snored' },
        ],
        ...overrides,
        funnelsFilter: { funnelVizType: FunnelVizType.Steps, ...overrides.funnelsFilter },
    })
}

const hedgehogBreakdown = { breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' as const } }

describe('FunnelStepsBarChart', () => {
    it('renders a bar per step with the canned counts and conversion percentages in the step legends', async () => {
        renderInsight({ query: stepsFunnelQuery() })

        await screen.findByTestId('funnel-steps-bar-chart')
        await screen.findByLabelText(/chart with 1 data series/i)

        // Canned steps: $pageview 100 → Napped 60 (60%) → Snored 30 (30%).
        const legends = screen.getAllByTestId('funnel-step-legend')
        expect(legends).toHaveLength(3)
        expect(legends[0].textContent).toContain('100')
        expect(legends[1].textContent).toContain('60%')
        expect(legends[2].textContent).toContain('30%')
    })

    it('renders one canvas series per breakdown value, with legend counts summed across values', async () => {
        renderInsight({ query: stepsFunnelQuery(hedgehogBreakdown) })

        await screen.findByTestId('funnel-steps-bar-chart')
        // Canned breakdown: Spike 70/42/21 + Bramble 30/18/9, plus the prepended Baseline series.
        await screen.findByLabelText(/chart with 3 data series/i)

        const legends = screen.getAllByTestId('funnel-step-legend')
        expect(legends).toHaveLength(3)
        expect(legends[0].textContent).toMatch(/100\spersons/)
        expect(legends[1].textContent).toMatch(/60\spersons/)
    })

    it('opens the persons modal for the clicked step, converted actors scoped via funnelStep', async () => {
        renderInsight({
            query: stepsFunnelQuery(),
            mocks: { additionalMockResponses: [stepsFunnelActorsEcho] },
        })

        await screen.findByLabelText(/chart with 1 data series/i)
        await chart.clickAtIndex(1, 3)

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual(['step2@example.com'])
        })
        expect(personsModal.title()).toMatch(/Completed step 2/)
    })

    it('scopes the persons modal to the clicked breakdown value via funnelStepBreakdown', async () => {
        renderInsight({
            query: stepsFunnelQuery(hedgehogBreakdown),
            mocks: { additionalMockResponses: [stepsFunnelActorsEcho] },
        })

        await screen.findByLabelText(/chart with 3 data series/i)
        await chart.clickAtIndex(1, 3)

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual(['step2-Spike@example.com'])
        })
        expect(personsModal.title()).toMatch(/Spike/)
    })

    it('opens the drop-off persons modal (negative funnelStep) from the legend inspect button', async () => {
        renderInsight({
            query: stepsFunnelQuery(),
            mocks: { additionalMockResponses: [stepsFunnelActorsEcho] },
        })

        await screen.findByLabelText(/chart with 1 data series/i)
        const droppedOffButtons = screen.getAllByTestId('funnel-inspect-dropped-off')
        fireEvent.click(droppedOffButtons[0])

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual(['step-2@example.com'])
        })
        expect(personsModal.title()).toMatch(/Dropped off at step 2/)
    })
})
