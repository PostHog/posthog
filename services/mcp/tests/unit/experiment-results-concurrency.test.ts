import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'

// Every metric is one /query/ call against a per-organization concurrency limit shared with the
// app, so a run with many metrics must not fire them all at once.
describe('experiment-results-get metric query concurrency', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    const metric = (uuid: string): Record<string, unknown> => ({
        kind: 'ExperimentMetric',
        metric_type: 'mean',
        uuid,
        source: { kind: 'EventsNode', event: '$pageview' },
    })
    const primaryUuids = Array.from({ length: 10 }, (_, i) => `primary-${i}`)
    const secondaryUuids = Array.from({ length: 6 }, (_, i) => `secondary-${i}`)
    const experiment = {
        id: 7,
        name: 'Checkout test',
        start_date: '2026-01-01T00:00:00Z',
        end_date: null,
        metrics: primaryUuids.map(metric),
        metrics_secondary: secondaryUuids.map(metric),
        saved_metrics: [],
    }

    it('keeps at most four metric queries in flight and returns results in metric order', async () => {
        let inFlight = 0
        let maxInFlight = 0
        const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
            if (url.includes('/experiments/7/')) {
                return new Response(JSON.stringify(experiment), { status: 200 })
            }
            const body = JSON.parse(init?.body as string)
            if (body.query?.kind !== 'ExperimentQuery') {
                return new Response(JSON.stringify({}), { status: 200 })
            }
            inFlight++
            maxInFlight = Math.max(maxInFlight, inFlight)
            await new Promise((resolve) => setTimeout(resolve, 0))
            inFlight--
            return new Response(JSON.stringify({ metric_uuid: body.query.metric.uuid }), { status: 200 })
        })
        vi.stubGlobal('fetch', fetchMock)

        const client = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })
        const result = await client
            .experiments({ projectId: '42' })
            .getMetricResults({ experimentId: 7, refresh: false })

        expect(result.success).toBe(true)
        if (!result.success) {
            return
        }
        expect(maxInFlight).toBe(4)
        expect(result.data.primaryMetricsResults.map((r) => (r as { metric_uuid: string }).metric_uuid)).toEqual(
            primaryUuids
        )
        expect(result.data.secondaryMetricsResults.map((r) => (r as { metric_uuid: string }).metric_uuid)).toEqual(
            secondaryUuids
        )
    })
})
