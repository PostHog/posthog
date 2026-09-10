import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'

import { ensureJsdom, getHogChart } from '@posthog/quill-charts/testing'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportPrimaryMetric } from './ReportPrimaryMetric'

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

function primaryMetricElement(container: HTMLElement): HTMLElement {
    const element = container.querySelector<HTMLElement>('[data-attr="report-primary-metric"]')
    if (!element) {
        throw new Error('Expected the primary metric to render')
    }
    return element
}

function trendsResponse(aggregatedValue: number, data: number[] = [4, 7]): Record<string, unknown> {
    return {
        result: [
            {
                label: 'Users affected',
                count: 7,
                data,
                days: ['2026-08-28', '2026-08-29'],
                labels: ['2026-08-28', '2026-08-29'],
                aggregated_value: aggregatedValue,
            },
        ],
    }
}

ensureJsdom()

describe('ReportPrimaryMetric', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
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
                    return [200, trendsResponse(42, [0, 1])]
                },
            },
        })

        const { container } = render(
            <ReportPrimaryMetric reportId="primary" metric={makeMetric({ role: 'primary', comparison })} />
        )

        const observation = within(primaryMetricElement(container))
        expect(await observation.findByText('42')).toBeInTheDocument()
        expect(observation.getByText('users')).toBeInTheDocument()
        const chart = await waitFor(() => {
            const element = container.querySelector<HTMLElement>('[data-attr="report-primary-metric-chart"]')
            if (!element) {
                throw new Error('Expected the observation chart to render')
            }
            return element
        })
        expect(chart).toHaveAttribute('data-chart-type', 'bar')
        expect(getHogChart(chart).yTicks().filter(Boolean)).toEqual(['0', '1'])
        await waitFor(() =>
            expect(requestedDisplays).toEqual(
                expect.arrayContaining([ChartDisplayType.BoldNumber, ChartDisplayType.ActionsBar])
            )
        )
        expect(requestedDisplays).toHaveLength(2)
    })

    it('reads the live figure against its comparison and names the window', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, trendsResponse(1248)],
            },
        })

        const { container } = render(
            <ReportPrimaryMetric
                reportId="live-meta"
                metric={makeMetric({ role: 'primary', comparison: { label: 'Previous 14 days', value: 832 } })}
            />
        )

        const observation = within(primaryMetricElement(container))
        expect(await observation.findByText('1,248')).toBeInTheDocument()
        expect(observation.getByText('Previous 14 days: 832 users')).toBeInTheDocument()
        expect(observation.getByText('Last 7 days')).toBeInTheDocument()

        const delta = container.querySelector('[data-attr="report-metric-delta"]')
        expect(delta).toHaveTextContent('+50%')
        expect(delta).toHaveAttribute('data-tone', 'bad')
    })

    it('keeps the saved comparison when a primary metric falls back after a failed refresh', async () => {
        jest.spyOn(console, 'error').mockImplementation()
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [500, { detail: 'Query failed' }],
            },
        })

        render(<ReportPrimaryMetric reportId="failed-primary" metric={makeMetric({ role: 'primary', comparison })} />)

        expect(await screen.findByText(/Couldn't refresh this metric/)).toBeInTheDocument()
        expect(screen.getByText('9')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()
    })

    it('falls back to the saved primary value when the live query returns no series', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': [200, { result: [] }],
            },
        })

        render(
            <ReportPrimaryMetric reportId="empty-series-primary" metric={makeMetric({ role: 'primary', comparison })} />
        )

        expect(
            await screen.findByText(/No value for this window\. Showing the latest saved value\./)
        ).toBeInTheDocument()
        expect(screen.getByText('9')).toBeInTheDocument()
        expect(screen.getByText('Previous window: 5 users')).toBeInTheDocument()
    })

    it('shows the saved primary value without a load error when the query is omitted', () => {
        const { container } = render(
            <ReportPrimaryMetric reportId="omitted-primary" metric={makeMetric({ role: 'primary', query: null })} />
        )

        expect(screen.getByText('9')).toBeInTheDocument()
        expect(screen.getByText('users')).toBeInTheDocument()
        expect(screen.getByText(/Measured/)).toHaveTextContent('Measured 2026-08-29T12:00:00Z')
        expect(container.querySelector('[data-attr="report-primary-metric-chart"]')).toBeNull()
        expect(screen.queryByText(/Couldn't load the trend/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Refresh the page to try again/)).not.toBeInTheDocument()
    })

    it('describes the count and names the window and filters behind it with a link to open the insight', () => {
        const filteredQuery = {
            ...query,
            source: { ...query.source, properties: [{ key: '$browser', value: 'Chrome', type: 'event' }] },
        }
        const { container } = render(
            <ReportPrimaryMetric
                reportId="source"
                metric={makeMetric({
                    role: 'primary',
                    query: filteredQuery,
                    caption: 'Unique users on the captured exception.',
                })}
            />
        )

        expect(screen.getByText('Unique users on the captured exception.')).toBeInTheDocument()
        const source = container.querySelector('[data-attr="report-primary-metric-source"]')
        expect(source).toHaveTextContent('Last 7 days · 1 filter')
        const open = container.querySelector<HTMLAnchorElement>('[data-attr="report-primary-metric-open"]')
        expect(open).toHaveTextContent('Open insight')
        expect(open?.getAttribute('href')).toContain('/insights/new')
    })

    it('names no query when the viewer cannot see it', () => {
        const { container } = render(
            <ReportPrimaryMetric reportId="no-source" metric={makeMetric({ role: 'primary', query: null })} />
        )

        expect(container.querySelector('[data-attr="report-primary-metric-source"]')).toBeNull()
    })

    it('marks a primary metric as not available when its query and snapshot are both absent', () => {
        render(
            <ReportPrimaryMetric
                reportId="redacted-primary"
                metric={makeMetric({ role: 'primary', query: null, value: null })}
            />
        )

        expect(screen.getByText('Not available')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't load this metric's trend/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Refresh the page to try again/)).not.toBeInTheDocument()
    })
})
