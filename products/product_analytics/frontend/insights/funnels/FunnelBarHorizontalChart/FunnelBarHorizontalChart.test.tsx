import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor, within } from '@testing-library/react'

import { clickAtIndex, setupJsdom } from '@posthog/quill-charts/testing'

import { FunnelLayout } from 'lib/constants'

import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    buildActorsResponse,
    buildFunnelsQuery,
    type MockResponse,
    personsModal,
    renderInsight,
} from '~/test/insight-testing'
import { FunnelVizType } from '~/types'

configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void

// No setupSyncRaf here: the stacked bars' hover-fade animation re-requests a frame until time
// advances, so a synchronous RAF mock recurses forever and crashes the chart on hover.
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

function horizontalFunnelQuery(overrides: Partial<FunnelsQuery> = {}): FunnelsQuery {
    return buildFunnelsQuery({
        series: [
            { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
            { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
            { kind: NodeKind.EventsNode, event: 'Snored', name: 'Snored' },
        ],
        ...overrides,
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
            layout: FunnelLayout.horizontal,
            ...overrides.funnelsFilter,
        },
    })
}

async function findStepCanvases(container: HTMLElement, count: number): Promise<HTMLCanvasElement[]> {
    return await waitFor(() => {
        const canvases = Array.from(container.querySelectorAll<HTMLCanvasElement>('canvas[aria-label]'))
        expect(canvases).toHaveLength(count)
        return canvases
    })
}

describe('FunnelBarHorizontalChart', () => {
    it('renders for layout=horizontal with one bar per step and the counts and percentages in each step row', async () => {
        renderInsight({ query: horizontalFunnelQuery() })

        const container = await screen.findByTestId('funnel-bar-horizontal')
        expect(screen.queryByTestId('funnel-steps-bar-chart')).not.toBeInTheDocument()

        await findStepCanvases(container, 3)

        // Canned steps: $pageview 100 → Napped 60 (60%) → Snored 30 (30%).
        expect(container.textContent).toMatch(/100\spersons/)
        expect(container.textContent).toMatch(/60\spersons\s\(60%\) completed step/)
        expect(container.textContent).toMatch(/40\spersons\s\(40%\) dropped off/)
    })

    it('stacks one segment per breakdown value plus the drop-off filler in each step bar', async () => {
        renderInsight({
            query: horizontalFunnelQuery({ breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' } }),
        })

        const container = await screen.findByTestId('funnel-bar-horizontal')
        const canvases = await findStepCanvases(container, 3)

        // Spike + Bramble segments + the filler series on every step.
        expect(canvases.map((canvas) => canvas.getAttribute('aria-label'))).toEqual(
            Array(3).fill('Chart with 3 data series')
        )
    })

    it.each([
        {
            kind: 'converted',
            buttonText: /^60\spersons$/,
            title: /Completed step 2/,
            actor: 'step2@example.com',
        },
        {
            kind: 'dropped off',
            buttonText: /^40\spersons$/,
            title: /Dropped off at step 2/,
            actor: 'step-2@example.com',
        },
    ])('opens the $kind persons modal from the step footer inspect button', async ({ buttonText, title, actor }) => {
        renderInsight({
            query: horizontalFunnelQuery(),
            mocks: { additionalMockResponses: [stepsFunnelActorsEcho] },
        })

        const container = await screen.findByTestId('funnel-bar-horizontal')
        fireEvent.click(within(container).getByText(buttonText))

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual([actor])
        })
        expect(personsModal.title()).toMatch(title)
    })

    it('clicking a breakdown segment opens the persons modal scoped to that breakdown value', async () => {
        renderInsight({
            query: horizontalFunnelQuery({ breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' } }),
            mocks: { additionalMockResponses: [stepsFunnelActorsEcho] },
        })

        const container = await screen.findByTestId('funnel-bar-horizontal')
        const canvases = await findStepCanvases(container, 3)

        // Click near the left edge of step 2's bar — inside the Spike segment (42% of the width).
        await clickAtIndex(canvases[1].parentElement!, 0, 1)

        await waitFor(() => {
            expect(personsModal.actorNames()).toEqual(['step2-Spike@example.com'])
        })
        expect(personsModal.title()).toMatch(/Spike/)
    })
})
