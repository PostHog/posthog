import '@testing-library/jest-dom'

import { cleanup, configure, screen, waitFor } from '@testing-library/react'

import { InsightVizNode, NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { buildTrendsQuery, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

// The full InsightViz tree is heavy to mount under jsdom, so the default 1s findBy timeout flakes on CI.
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

afterEach(() => {
    cleanup()
})

describe('TrendInsight', () => {
    it.each<[string, QueryContext<InsightVizNode> | undefined, string]>([
        ['the context copy', { emptyStateHeading: 'No calls to this flag' }, 'No calls to this flag'],
        ['the default copy', undefined, 'No insight results'],
    ])('an empty table shows %s', async (_name, context, expectedText) => {
        renderInsight({
            query: buildTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsTable } }),
            context,
            mocks: {
                additionalMockResponses: [
                    {
                        match: (query) => query.kind === NodeKind.TrendsQuery,
                        response: { results: [] } as unknown as TrendsQueryResponse,
                    },
                ],
            },
        })

        expect(await screen.findByText(expectedText)).toBeInTheDocument()
    })

    it('a region map with no series renders', async () => {
        const { container } = renderInsight({
            query: buildTrendsQuery({
                series: [],
                breakdownFilter: {
                    breakdowns: [
                        { property: '$geoip_country_code', type: 'event' },
                        { property: '$geoip_subdivision_1_code', type: 'event' },
                    ],
                },
                trendsFilter: { display: ChartDisplayType.WorldMap },
            }),
        })

        await waitFor(() => expect(container.querySelector('.RegionMap')).toBeInTheDocument())
    })
})
