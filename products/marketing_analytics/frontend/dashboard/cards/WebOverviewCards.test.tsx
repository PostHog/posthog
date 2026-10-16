import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'

import { WebOverviewCards } from './WebOverviewCards'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ loadData: jest.fn() }),
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic', () => ({
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID: 'marketing-analytics-tiles',
}))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: () => ({}) }))
jest.mock('./useCardExpansion', () => ({ useCardExpansion: () => (spec: unknown) => spec }))
jest.mock('./MarketingMetricCard', () => ({ MarketingMetricCard: () => null }))
jest.mock('@posthog/lemon-ui', () => ({
    LemonBanner: ({ children }: { children: React.ReactNode }) => <div role="alert">{children}</div>,
}))

describe('WebOverviewCards', () => {
    afterEach(cleanup)

    it.each([
        ['failed-query', 'current-query', 'failed-query'],
        [undefined, 'current-query', 'current-query'],
        [undefined, null, null],
    ])('identifies the failed request with error ID %s and request ID %s', (errorId, requestId, expected) => {
        jest.mocked(useValues).mockReturnValue({
            responseLoading: false,
            responseError: 'Query failed',
            responseErrorObject: { queryId: errorId },
            queryId: requestId,
            response: { query_status: { id: 'previous-successful-query' } },
        })
        render(
            <WebOverviewCards
                query={{ kind: NodeKind.WebOverviewQuery, properties: [] }}
                dataNodeKey="marketing-dashboard-web-overview"
                select={() => []}
                numSkeletons={1}
                labelFromKey={(key) => key}
            />
        )
        const error = screen.getByRole('alert')
        expect(error.textContent?.match(/Query ID: (.+)/)?.[1] ?? null).toBe(expected)
        expect(error.textContent).not.toContain('previous-successful-query')
    })
})
