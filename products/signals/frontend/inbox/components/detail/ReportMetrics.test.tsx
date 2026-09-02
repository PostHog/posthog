import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportMetrics } from './ReportMetrics'

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

const comparison = { label: 'Previous window', value: 5 }

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
        comparison: null,
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

describe('ReportMetrics', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('renders no metric surface when the report has no metrics', () => {
        const { container } = render(<ReportMetrics reportId="no-metrics" />)

        expect(container).toBeEmptyDOMElement()
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

        render(<ReportMetrics reportId="live-supporting" metrics={[makeMetric({ comparison })]} />)

        expect(await screen.findByText('42 users')).toBeInTheDocument()
        expect(screen.queryByText('9 users')).not.toBeInTheDocument()
        expect(screen.queryByText('Previous window: 5 users')).not.toBeInTheDocument()
        expect(requests).toBe(1)
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

        render(<ReportMetrics reportId="default-supporting" metrics={[makeMetric({ role: undefined, comparison })]} />)

        expect(await screen.findByText('42 users')).toBeInTheDocument()
        expect(screen.queryByText('9 users')).not.toBeInTheDocument()
        expect(screen.queryByText('Previous window: 5 users')).not.toBeInTheDocument()
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

        render(<ReportMetrics reportId="loading-supporting" metrics={[makeMetric({ comparison })]} />)

        expect(screen.getByText('9 users')).toBeInTheDocument()
        expect(screen.getByText('Refreshing current value')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()

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
            <ReportMetrics
                reportId="unrunnable-supporting"
                metrics={[makeMetric({ comparison, query: unrunnableQuery })]}
            />
        )

        expect(await screen.findByText(/No current value/)).toHaveTextContent(
            'No current value. Showing the latest saved value.'
        )
        expect(screen.getByText('9 users')).toBeInTheDocument()
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

        render(<ReportMetrics reportId="failed-supporting" metrics={[makeMetric({ comparison })]} />)

        expect(await screen.findByText(/Couldn't refresh this metric/)).toHaveTextContent(
            "Couldn't refresh this metric. Showing the latest saved value. Refresh the page to try again."
        )
        expect(screen.getByText('9 users')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()
    })

    it('renders a live zero instead of falling back to a nonzero snapshot', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(0)],
            },
        })

        render(<ReportMetrics reportId="zero-supporting" metrics={[makeMetric()]} />)

        expect(await screen.findByText('0 users')).toBeInTheDocument()
        expect(screen.queryByText('9 users')).not.toBeInTheDocument()
    })

    it('formats a live scaled percentage before replacing its snapshot', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(0.34)],
            },
        })

        render(
            <ReportMetrics
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

    it('uses a whole-window total for the primary headline and buckets for its chart', async () => {
        const requestedDisplays: Array<string | undefined> = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { trendsFilter?: { display?: string } }
                    }
                    requestedDisplays.push(body.query?.trendsFilter?.display)
                    return [200, trendsResponse(42)]
                },
            },
        })

        const { container } = render(
            <ReportMetrics reportId="primary" metrics={[makeMetric({ role: 'primary', comparison })]} />
        )

        expect(await screen.findByText('42 users')).toBeInTheDocument()
        expect(screen.queryByText('Previous window: 5 users')).not.toBeInTheDocument()
        expect(container.querySelector('.InsightCard__viz--ActionsBar')).not.toBeNull()
        await waitFor(() =>
            expect(requestedDisplays).toEqual(
                expect.arrayContaining([ChartDisplayType.BoldNumber, ChartDisplayType.ActionsBar])
            )
        )
        expect(requestedDisplays).toHaveLength(2)
    })

    it('keeps the saved comparison when a primary metric falls back after a failed refresh', async () => {
        jest.spyOn(console, 'error').mockImplementation()
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [500, { detail: 'Query failed' }],
            },
        })

        render(<ReportMetrics reportId="failed-primary" metrics={[makeMetric({ role: 'primary', comparison })]} />)

        expect(await screen.findByText(/Couldn't refresh this metric/)).toBeInTheDocument()
        expect(screen.getByText('9 users')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()
    })

    it('falls back to the saved primary value when the live query returns no series', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, { result: [] }],
            },
        })

        render(
            <ReportMetrics reportId="empty-series-primary" metrics={[makeMetric({ role: 'primary', comparison })]} />
        )

        expect(
            await screen.findByText(/No value for this window\. Showing the latest saved value\./)
        ).toBeInTheDocument()
        expect(screen.getByText('9 users')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()
    })

    it('shows the saved primary value without a load error when the query is omitted', () => {
        render(<ReportMetrics reportId="omitted-primary" metrics={[makeMetric({ role: 'primary', query: null })]} />)

        expect(screen.getByText('9 users')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't load this metric's trend/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Refresh the page to try again/)).not.toBeInTheDocument()
    })

    it('marks a primary metric as not available when its query and snapshot are both absent', () => {
        render(
            <ReportMetrics
                reportId="redacted-primary"
                metrics={[makeMetric({ role: 'primary', query: null, value: null })]}
            />
        )

        expect(screen.getByText('Not available')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't load this metric's trend/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Refresh the page to try again/)).not.toBeInTheDocument()
    })
})
