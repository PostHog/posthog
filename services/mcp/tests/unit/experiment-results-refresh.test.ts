import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'

// The experiment query runners keep results for 24 hours. `blocking` serves that cache while it is
// fresh, so refresh=true must send `force_blocking` or the agent gets day-old results back.
describe('experiment-results-get refresh', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    const experiment = {
        id: 7,
        name: 'Checkout test',
        start_date: '2026-01-01T00:00:00Z',
        end_date: null,
        metrics: [
            {
                kind: 'ExperimentMetric',
                metric_type: 'mean',
                uuid: 'primary-1',
                source: { kind: 'EventsNode', event: '$pageview' },
            },
        ],
        metrics_secondary: [
            {
                kind: 'ExperimentMetric',
                metric_type: 'mean',
                uuid: 'secondary-1',
                source: { kind: 'EventsNode', event: 'purchase' },
            },
        ],
        saved_metrics: [],
    }

    const queryRefreshModes = async (refresh: boolean): Promise<unknown[]> => {
        const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
            url.includes('/experiments/7/')
                ? new Response(JSON.stringify(experiment), { status: 200 })
                : new Response(JSON.stringify({}), { status: 200 })
        )
        vi.stubGlobal('fetch', fetchMock)

        const client = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })
        const result = await client.experiments({ projectId: '42' }).getMetricResults({ experimentId: 7, refresh })
        expect(result.success).toBe(true)

        const queryCalls = fetchMock.mock.calls.filter(([url]) => url.endsWith('/query/'))
        // One exposure query, one primary metric query, one secondary metric query.
        expect(queryCalls).toHaveLength(3)
        return queryCalls.map(([, init]) => JSON.parse(init?.body as string).refresh)
    }

    it.each([
        [true, 'force_blocking'],
        [false, undefined],
    ])('sends refresh=%s to every query as %s', async (refresh, expectedMode) => {
        expect(await queryRefreshModes(refresh)).toEqual([expectedMode, expectedMode, expectedMode])
    })
})
