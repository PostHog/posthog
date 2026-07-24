import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    buildFunnelsQuery,
    getHogChart,
    type MockResponse,
    type QueryBody,
    renderInsight,
} from '~/test/insight-testing'
import { type FunnelTimeToConvertFixture, funnelTimeToConvertBins } from '~/test/insight-testing/test-data'
import { FunnelVizType } from '~/types'

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

const timeToConvertQuery = (extra: Partial<FunnelsQuery> = {}): FunnelsQuery =>
    buildFunnelsQuery({ ...extra, funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert } })

const isTimeToConvertQuery = (query: QueryBody): boolean =>
    query.kind === NodeKind.FunnelsQuery && query.funnelsFilter?.funnelVizType === 'time_to_convert'

type TimeToConvertResults =
    | (FunnelTimeToConvertFixture & { median_conversion_time?: number })
    | (FunnelTimeToConvertFixture & { compare_label: string })[]

function mockTimeToConvertResults(results: TimeToConvertResults): MockResponse {
    return { match: isTimeToConvertQuery, response: { results } as MockResponse['response'] }
}

describe('FunnelHistogramChart', () => {
    it('renders one bar per time-to-convert bin, labelled with each bin share of conversions', async () => {
        renderInsight({ query: timeToConvertQuery() })

        await screen.findByLabelText(/chart with 1 data series/i)

        // Canned bins hold 4/10/4/2 of 20 conversions → 20% / 50% / 20% / 10%.
        await waitFor(() => {
            expect(
                getHogChart()
                    .valueLabels()
                    .map((label) => label.text)
            ).toEqual(['20.0%', '50.0%', '20.0%', '10.0%'])
        })
    })

    it('shows the median time to convert from the response in the canvas label', async () => {
        renderInsight({
            query: timeToConvertQuery(),
            mocks: {
                additionalMockResponses: [
                    mockTimeToConvertResults({ ...funnelTimeToConvertBins, median_conversion_time: 138 }),
                ],
            },
        })

        await screen.findByLabelText(/chart with 1 data series/i)
        expect(screen.getByText('Median time to convert')).toBeInTheDocument()
        expect(screen.getByText('2m 18s')).toBeInTheDocument()
    })

    it('renders the empty state instead of a chart when the response has fewer than two bins', async () => {
        renderInsight({
            query: timeToConvertQuery(),
            mocks: {
                additionalMockResponses: [mockTimeToConvertResults({ bins: [[0, 4]], average_conversion_time: 0 })],
            },
        })

        await screen.findByTestId('insight-empty-state')
        expect(screen.queryByLabelText(/chart with/i)).not.toBeInTheDocument()
    })

    it('splits a compare response into current and previous series and drops the per-bin labels', async () => {
        renderInsight({
            query: timeToConvertQuery({ compareFilter: { compare: true } }),
            mocks: {
                additionalMockResponses: [
                    mockTimeToConvertResults([
                        { ...funnelTimeToConvertBins, compare_label: 'current' },
                        {
                            bins: [
                                [0, 2],
                                [120, 5],
                                [240, 2],
                                [360, 1],
                            ],
                            average_conversion_time: 150,
                            compare_label: 'previous',
                        },
                    ]),
                ],
            },
        })

        await screen.findByLabelText(/chart with 2 data series/i)
        expect(getHogChart().valueLabels()).toHaveLength(0)
    })
})
