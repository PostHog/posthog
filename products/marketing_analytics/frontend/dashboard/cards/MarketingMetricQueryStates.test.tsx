import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { ConversionValueLoaded } from './ConversionValueLoaded'
import { MarketingMetricCardProps } from './MarketingMetricCard'
import { RetentionCards } from './RetentionCards'
import { RevenueValueCard } from './RevenueValueCard'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('../marketingDashboardLogic', () => ({ marketingDashboardLogic: {} }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic', () => ({
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID: 'marketing-analytics-tiles',
}))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: (props: unknown) => props }))
jest.mock('./useCardExpansion', () => ({ useCardExpansion: () => (spec: unknown) => spec }))
jest.mock('./MarketingMetricCard', () => ({
    MarketingMetricCard: ({ spec, loading, labelFromKey }: MarketingMetricCardProps) =>
        loading ? (
            <div role="status">Loading</div>
        ) : spec?.kind === 'metric' ? (
            <div>
                {labelFromKey(spec.item.key)}: <span data-attr="metric-value">{spec.item.value}</span>
            </div>
        ) : spec?.kind === 'notice' ? (
            <div>{spec.message}</div>
        ) : null,
}))
jest.mock('@posthog/lemon-ui', () => ({
    LemonBanner: ({ children, action }: { children: React.ReactNode; action: { onClick: () => void } }) => (
        <div role="alert">
            {children}
            <button onClick={action.onClick}>Retry</button>
        </div>
    ),
}))

const query: TrendsQuery = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: 'purchase' }] }

describe('Marketing metric query states', () => {
    const loadData = jest.fn()
    const loadTraffic = jest.fn()
    let queryState: Record<string, unknown>
    let trafficState: Record<string, unknown>

    beforeEach(() => {
        queryState = { responseLoading: false, responseError: 'Query failed', queryId: 'failed-query' }
        trafficState = { responseLoading: false, response: { results: [{ key: 'visitors', value: 10, previous: 10 }] } }
        jest.mocked(useValues).mockImplementation((logic) => {
            const key = (logic as unknown as { key?: string }).key
            return key === 'marketing-dashboard-retention-traffic'
                ? trafficState
                : key
                  ? queryState
                  : { retentionQuery: {}, retentionTrafficQuery: {}, retentionAcquisitionRange: { clamped: true } }
        })
        jest.mocked(useActions).mockImplementation((logic) => ({
            loadData:
                (logic as unknown as { key?: string }).key === 'marketing-dashboard-retention-traffic'
                    ? loadTraffic
                    : loadData,
        }))
        loadData.mockClear()
        loadTraffic.mockClear()
    })

    afterEach(cleanup)

    it.each([
        ['revenue', () => <RevenueValueCard query={query} />],
        ['conversion value', () => <ConversionValueLoaded query={query} keys={['conversion_value']} />],
        ['retention', () => <RetentionCards only="acquired" />],
    ])('keeps failed, loading, and successful zero %s distinct', (_, card) => {
        const failed = queryState
        queryState = {}
        const { rerender } = render(card())
        expect(screen.getByRole('status')).toHaveTextContent('Loading')
        expect(screen.queryByTestId('metric-value')).not.toBeInTheDocument()
        queryState = failed
        rerender(card())
        expect(screen.getByRole('alert')).toHaveTextContent('failed-query')
        expect(screen.queryByTestId('metric-value')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('Retry'))
        expect(loadData).toHaveBeenCalledWith('force_async')

        queryState = { ...queryState, responseLoading: true }
        rerender(card())
        expect(screen.getByRole('status')).toHaveTextContent('Loading')
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
        expect(screen.queryByTestId('metric-value')).not.toBeInTheDocument()

        queryState = {
            responseLoading: false,
            response: { results: [{ action: { order: 0 }, aggregated_value: 0 }], summary: [] },
        }
        rerender(card())
        expect(screen.getByTestId('metric-value')).toHaveTextContent('0')
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('waits for the denominator and retries only its failed query', () => {
        queryState = { response: { summary: [] } }
        trafficState = { responseLoading: true }
        const { rerender } = render(<RetentionCards only="newVisitorShare" />)
        expect(screen.getByRole('status')).toBeInTheDocument()
        trafficState = { responseError: 'Query failed', queryId: 'traffic-query' }
        rerender(<RetentionCards only="newVisitorShare" />)
        expect(screen.getByRole('alert')).toHaveTextContent('traffic-query')
        fireEvent.click(screen.getByText('Retry'))
        expect(loadTraffic).toHaveBeenCalledWith('force_async')
        expect(loadData).not.toHaveBeenCalled()
    })

    it('explains the bounded range when there are no visitors to compare', () => {
        queryState = { response: { summary: [] } }
        trafficState = { response: { results: [{ key: 'visitors', value: 0 }] } }
        render(<RetentionCards only="newVisitorShare" />)
        expect(screen.getByText(/This metric covers the last 90 days of the selected range/)).toBeInTheDocument()
    })

    it('renders the population median supplied by the backend and labels the bounded range', () => {
        queryState = {
            response: {
                overallMedianReturnDays: 1,
                summary: [
                    { acquired: 9, returners: 9, medianReturnDays: 1 },
                    { acquired: 1, returners: 1, medianReturnDays: 30 },
                ],
            },
        }
        render(<RetentionCards only="medianReturnDays" />)
        expect(screen.getByTestId('metric-value')).toHaveTextContent(/^1$/)
        expect(screen.getByText('Last 90 days of selected range')).toBeInTheDocument()
    })
})
