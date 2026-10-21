import '@testing-library/jest-dom'

import { cleanup, configure, screen } from '@testing-library/react'

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
})
