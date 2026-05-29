import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { setupJsdom, setupSyncRaf } from 'lib/hog-charts/testing'

import { LifecycleQuery, LifecycleQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { chart, type InsightQuery, type MockResponse, personsModal, renderInsight } from '~/test/insight-testing'

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

const HOG_CHARTS_FLAG = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_LIFECYCLE]: true }

const LIFECYCLE_DAYS = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const LIFECYCLE_LABELS = ['10-Jun', '11-Jun', '12-Jun', '13-Jun', '14-Jun']

const buildLifecycleSeries = (status: 'new' | 'returning' | 'resurrecting' | 'dormant', data: number[]): object => ({
    action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
    label: `$pageview - ${status}`,
    count: data.reduce((a, b) => a + b, 0),
    aggregated_value: data.reduce((a, b) => a + b, 0),
    data,
    labels: LIFECYCLE_LABELS,
    days: LIFECYCLE_DAYS,
    status,
})

const lifecycleResponse: LifecycleQueryResponse = {
    results: [
        buildLifecycleSeries('new', [10, 12, 8, 14, 9]),
        buildLifecycleSeries('returning', [5, 6, 7, 5, 6]),
        buildLifecycleSeries('resurrecting', [2, 3, 4, 2, 3]),
        buildLifecycleSeries('dormant', [-3, -4, -2, -5, -3]),
    ],
} as LifecycleQueryResponse

const buildLifecycleQuery = (overrides: Partial<LifecycleQuery> = {}): LifecycleQuery => ({
    kind: NodeKind.LifecycleQuery,
    series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
    ...overrides,
})

const lifecycleMocks: MockResponse[] = [
    {
        match: (q) => q.kind === NodeKind.LifecycleQuery,
        response: lifecycleResponse,
    },
]

describe('TrendsLifecycleChart', () => {
    it('renders a stacked bar series for each lifecycle status', async () => {
        renderInsight({
            query: buildLifecycleQuery() as unknown as InsightQuery,
            featureFlags: HOG_CHARTS_FLAG,
            mocks: { additionalMockResponses: lifecycleMocks },
        })

        await waitFor(() => {
            expect(screen.getByTestId('trend-lifecycle-graph')).toBeInTheDocument()
        })
        await waitFor(() => {
            expect(screen.getByRole('img', { name: /chart with 4 data series/i })).toBeInTheDocument()
        })
    })

    it('shows the shortened lifecycle status in the tooltip rows', async () => {
        renderInsight({
            query: buildLifecycleQuery() as unknown as InsightQuery,
            featureFlags: HOG_CHARTS_FLAG,
            mocks: { additionalMockResponses: lifecycleMocks },
        })

        await screen.findByTestId('trend-lifecycle-graph')
        const tooltip = await chart.hoverTooltip(2)
        // Lifecycle status names appear capitalized — "New", "Returning", "Resurrecting", "Dormant".
        expect(tooltip.row('New')).toBeTruthy()
        expect(tooltip.row('Returning')).toBeTruthy()
        expect(tooltip.row('Resurrecting')).toBeTruthy()
        expect(tooltip.row('Dormant')).toBeTruthy()
    })

    it('uses "Users" as the group type label in the tooltip', async () => {
        renderInsight({
            query: buildLifecycleQuery() as unknown as InsightQuery,
            featureFlags: HOG_CHARTS_FLAG,
            mocks: { additionalMockResponses: lifecycleMocks },
        })

        await screen.findByTestId('trend-lifecycle-graph')
        const tooltip = await chart.hoverTooltip(2)
        expect(tooltip.element.textContent).toMatch(/Users/)
    })

    it('renders InsightEmptyState when every series count is zero', async () => {
        renderInsight({
            query: buildLifecycleQuery() as unknown as InsightQuery,
            featureFlags: HOG_CHARTS_FLAG,
            mocks: {
                additionalMockResponses: [
                    {
                        match: (q) => q.kind === NodeKind.LifecycleQuery,
                        response: {
                            results: [
                                buildLifecycleSeries('new', [0, 0, 0, 0, 0]),
                                buildLifecycleSeries('returning', [0, 0, 0, 0, 0]),
                                buildLifecycleSeries('resurrecting', [0, 0, 0, 0, 0]),
                                buildLifecycleSeries('dormant', [0, 0, 0, 0, 0]),
                            ],
                        } as LifecycleQueryResponse,
                    },
                ],
            },
        })

        await waitFor(() => {
            expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
        })
    })

    it('falls back to the legacy renderer when the flag is off', async () => {
        renderInsight({
            query: buildLifecycleQuery() as unknown as InsightQuery,
            featureFlags: {},
            mocks: { additionalMockResponses: lifecycleMocks },
        })

        // Without the flag the hog-charts data-attr is never rendered; the Chart.js LineGraph
        // renders a <canvas> instead.
        await waitFor(() => {
            expect(screen.queryByTestId('trend-lifecycle-graph')).not.toBeInTheDocument()
        })
    })
})
