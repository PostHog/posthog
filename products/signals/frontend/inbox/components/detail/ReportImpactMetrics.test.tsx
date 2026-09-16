import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportImpactMetrics } from './ReportImpactMetrics'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

const query = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        dateRange: { date_from: '-7d', date_to: null },
        interval: 'day',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$autocapture',
                name: '$autocapture',
                math: BaseMathType.UniqueUsers,
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsBar },
    },
}

const percentageQuery = {
    ...query,
    source: {
        ...query.source,
        trendsFilter: {
            ...query.source.trendsFilter,
            aggregationAxisFormat: 'percentage_scaled',
        },
    },
}

function makeMetric(overrides: Partial<ReportMetricApi> = {}): ReportMetricApi {
    return {
        metric_id: 'affected-users',
        title: 'Users affected',
        kind: 'affected_users',
        role: 'supporting',
        value: 9,
        value_at: '2026-08-29T12:00:00Z',
        value_format: 'count',
        unit: 'users',
        query,
        caption: null,
        ...overrides,
    }
}

function trendsResponse(aggregatedValue: number): Record<string, unknown> {
    return {
        result: [
            {
                label: 'Users affected',
                count: 7,
                data: [4, 7],
                days: ['2026-08-28', '2026-08-29'],
                labels: ['2026-08-28', '2026-08-29'],
                aggregated_value: aggregatedValue,
            },
        ],
    }
}

describe('ReportImpactMetrics', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('replaces a supporting snapshot with its live whole-window value', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => {
                    requests += 1
                    return [200, trendsResponse(42)]
                },
            },
        })

        render(<ReportImpactMetrics reportId="live-supporting" metrics={[makeMetric()]} />)

        expect(await screen.findByText('42')).toBeInTheDocument()
        expect(screen.queryByText('9')).not.toBeInTheDocument()
        expect(screen.getByText('Last 7 days')).toBeInTheDocument()
        expect(screen.queryByText('Current window')).not.toBeInTheDocument()
        expect(requests).toBe(1)
    })

    it('sets the tile unit apart from its figure', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(3912)],
            },
        })

        render(
            <ReportImpactMetrics
                reportId="unit-supporting"
                metrics={[makeMetric({ metric_id: 'dead-clicks', title: 'Dead clicks', unit: 'clicks' })]}
            />
        )

        expect(await screen.findByText('3,912')).toBeInTheDocument()
        expect(screen.getByText('clicks')).toBeInTheDocument()
    })

    it('uses the generated supporting role default when role is omitted', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => {
                    requests += 1
                    return [200, trendsResponse(42)]
                },
            },
        })

        render(<ReportImpactMetrics reportId="default-supporting" metrics={[makeMetric({ role: undefined })]} />)

        expect(await screen.findByText('42')).toBeInTheDocument()
        expect(screen.queryByText('9')).not.toBeInTheDocument()
        expect(requests).toBe(1)
    })

    it('keeps the saved supporting value visible while its live value loads', async () => {
        let finishRequest: ((response: [number, Record<string, unknown>]) => void) | undefined
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () =>
                    new Promise<[number, Record<string, unknown>]>((resolve) => {
                        finishRequest = resolve
                    }),
            },
        })

        render(<ReportImpactMetrics reportId="loading-supporting" metrics={[makeMetric()]} />)

        expect(screen.getByText('9')).toBeInTheDocument()
        expect(screen.getByText('Refreshing current value')).toBeInTheDocument()

        await waitFor(() => expect(finishRequest).not.toBeUndefined())
        await act(async () => finishRequest?.([200, trendsResponse(10)]))
    })

    it('settles a supporting metric to its saved value when the live query never runs', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => {
                    requests += 1
                    return [200, trendsResponse(42)]
                },
            },
        })

        // An invalid RE2 regex filter makes the frontend refuse to run the query, so the loader
        // settles with a null response and no request. The card must leave the loading state.
        const unrunnableQuery = {
            ...query,
            source: {
                ...query.source,
                series: [
                    { ...query.source.series[0], properties: [{ key: '$current_url', operator: 'regex', value: '(' }] },
                ],
            },
        }

        render(
            <ReportImpactMetrics reportId="unrunnable-supporting" metrics={[makeMetric({ query: unrunnableQuery })]} />
        )

        expect(await screen.findByText(/No current value/)).toHaveTextContent(
            'No current value. Showing the latest saved value.'
        )
        expect(screen.getByText('9')).toBeInTheDocument()
        expect(screen.queryByText('Refreshing current value')).not.toBeInTheDocument()
        expect(screen.queryByText('Loading current value')).not.toBeInTheDocument()
        expect(requests).toBe(0)
    })

    it('explains when a supporting refresh failed and keeps its saved value', async () => {
        jest.spyOn(console, 'error').mockImplementation()
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [500, { detail: 'Query failed' }],
            },
        })

        render(<ReportImpactMetrics reportId="failed-supporting" metrics={[makeMetric()]} />)

        expect(await screen.findByText(/Couldn't refresh this metric/)).toHaveTextContent(
            "Couldn't refresh this metric. Showing the latest saved value. Refresh the page to try again."
        )
        expect(screen.getByText('9')).toBeInTheDocument()
    })

    it('renders a live zero instead of falling back to a nonzero snapshot', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(0)],
            },
        })

        render(<ReportImpactMetrics reportId="zero-supporting" metrics={[makeMetric()]} />)

        expect(await screen.findByText('0')).toBeInTheDocument()
        expect(screen.queryByText('9')).not.toBeInTheDocument()
    })

    it('formats a live scaled percentage before replacing its snapshot', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(0.34)],
            },
        })

        render(
            <ReportImpactMetrics
                reportId="scaled-supporting"
                metrics={[
                    makeMetric({
                        metric_id: 'conversion-rate',
                        title: 'Conversion rate',
                        kind: 'conversion_rate',
                        value: 0.12,
                        value_format: 'percentage_scaled',
                        unit: null,
                        query: percentageQuery,
                    }),
                ]}
            />
        )

        expect(await screen.findByText('34%')).toBeInTheDocument()
        expect(screen.queryByText('12%')).not.toBeInTheDocument()
    })
})
