import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { NodeKind, ResultCustomizationBy } from '~/queries/schema/schema-general'
import { buildTrendsQuery, getHogChart, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

configure({ asyncUtilTimeout: 3000 })

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

const slopeQuery = (extra?: Parameters<typeof buildTrendsQuery>[0]): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.SlopeGraph }, ...extra })

const slopeResult = (label: string, data: number[], order: number = 0): Record<string, unknown> => ({
    action: { id: `$${label.toLowerCase()}`, type: 'events', name: label, order },
    label,
    count: data.reduce((a, b) => a + b, 0),
    data,
    labels: data.map((_, i) => `Day ${i + 1}`),
    days: data.map((_, i) => `2024-06-0${i + 1}`),
})

const mockResults = (results: Record<string, unknown>[]): Parameters<typeof renderInsight>[0]['mocks'] => ({
    additionalMockResponses: [{ match: (q) => q.kind === NodeKind.TrendsQuery, response: { results } as never }],
})

describe('TrendsSlopeChart', () => {
    it('drops single-point series and renders only slopeable ones', async () => {
        renderInsight({
            query: slopeQuery(),
            mocks: mockResults([slopeResult('Pageview', [10, 90]), slopeResult('Napped', [5], 1)]),
        })

        await waitFor(
            () => {
                expect(screen.getByLabelText(/chart with 1 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        const labels = getHogChart().slopeValueLabels()
        expect(labels.map((l) => ({ side: l.side, text: l.text }))).toEqual([
            { side: 'start', text: '10' },
            { side: 'end', text: '90' },
        ])
    })

    it('renders InsightEmptyState when no series has two points', async () => {
        renderInsight({
            query: slopeQuery(),
            mocks: mockResults([slopeResult('Pageview', [5])]),
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('insight-empty-state')).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        expect(screen.queryByLabelText(/chart with/i)).not.toBeInTheDocument()
    })

    it('drops series hidden via result customizations', async () => {
        renderInsight({
            query: slopeQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                    { kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' },
                ],
                trendsFilter: {
                    display: ChartDisplayType.SlopeGraph,
                    resultCustomizationBy: ResultCustomizationBy.Position,
                    resultCustomizations: {
                        1: { assignmentBy: ResultCustomizationBy.Position, hidden: true },
                    },
                },
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByLabelText(/chart with 1 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
    })

    it('formats slope value labels with the insight aggregation axis format', async () => {
        renderInsight({
            query: slopeQuery({
                trendsFilter: { display: ChartDisplayType.SlopeGraph, aggregationAxisFormat: 'percentage' },
            }),
        })

        await waitFor(
            () => {
                expect(screen.getByLabelText(/chart with 1 data series/i)).toBeInTheDocument()
            },
            { timeout: 5000 }
        )
        // Canned Pageview data runs 45 → 95; the slope shows first and last values.
        const texts = getHogChart()
            .slopeValueLabels()
            .map((l) => l.text)
        expect(texts).toEqual(expect.arrayContaining(['45%', '95%']))
    })
})
