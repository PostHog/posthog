import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { Query } from '~/queries/Query/Query'
import { MetricsHistogramQuery, MetricsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

const METRICS_QUERY: MetricsQuery = {
    kind: NodeKind.MetricsQuery,
    clauses: [{ name: 'a', metricName: 'request_duration', aggregation: 'sum' }],
    dateRange: { date_from: '-1h' },
}

const HISTOGRAM_QUERY: MetricsHistogramQuery = {
    kind: NodeKind.MetricsHistogramQuery,
    metricName: 'request_duration',
    dateRange: { date_from: '-1h' },
}

describe('metrics query nodes', () => {
    let queryCalls: number

    beforeEach(() => {
        queryCalls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => {
                    queryCalls++
                    return [200, { results: [] }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('loads a failed time series again from its error banner', async () => {
        let queryCalls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () =>
                    ++queryCalls === 1 ? [500, { detail: 'ClickHouse was busy' }] : [200, { results: [] }],
            },
        })
        const { findAllByText, findByText, queryByText } = render(<Query query={METRICS_QUERY} readOnly />)
        await findByText('ClickHouse was busy')

        // The banner renders its action twice and shows one, depending on its width.
        ;(await findAllByText('Try again'))[0].click()

        await waitFor(() => expect(queryCalls).toBe(2))
        await waitFor(() => expect(queryByText('ClickHouse was busy')).toBeNull())
    })

    it.each([
        ['time series in a dashboard tile', METRICS_QUERY, true, false],
        ['time series in the insight scene opened from a dashboard', METRICS_QUERY, false, true],
        ['heatmap in a dashboard tile', HISTOGRAM_QUERY, true, false],
        ['heatmap in the insight scene opened from a dashboard', HISTOGRAM_QUERY, false, true],
    ])('%s', (_name, query, embedded, expectMinHeight) => {
        const { container } = render(
            <Query
                query={query}
                readOnly
                embedded={embedded}
                context={{ insightProps: { dashboardItemId: 'abc123' as InsightShortId, dashboardId: 1 } }}
            />
        )
        expect(container.querySelector('.min-h-\\[200px\\]') !== null).toBe(expectMinHeight)
    })

    // React can render a node many times before it commits one. Each of those renders mounts the node's
    // logic, so every render of the same query must reach the same logic and load once.
    it.each([
        ['time series', METRICS_QUERY],
        ['heatmap', HISTOGRAM_QUERY],
    ])('%s nodes with the same query share one load', async (_name, query) => {
        const { container } = render(
            <>
                <Query query={query} readOnly />
                <Query query={{ ...query }} readOnly />
            </>
        )
        await waitFor(() => expect(queryCalls).toBeGreaterThan(0))
        await waitFor(() => expect(container.querySelector('.Spinner')).toBeNull())
        expect(queryCalls).toBe(1)
    })

    it('saved insights with the same query keep separate logics', async () => {
        const { container } = render(
            <>
                <Query
                    query={METRICS_QUERY}
                    readOnly
                    context={{ insightProps: { dashboardItemId: 'tile-a' as InsightShortId } }}
                />
                <Query
                    query={METRICS_QUERY}
                    readOnly
                    context={{ insightProps: { dashboardItemId: 'tile-b' as InsightShortId } }}
                />
            </>
        )
        await waitFor(() => expect(container.querySelector('.Spinner')).toBeNull())
        expect(queryCalls).toBe(2)
    })
})
