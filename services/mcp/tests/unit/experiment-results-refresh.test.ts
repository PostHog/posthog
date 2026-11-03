import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { handleToolError } from '@/lib/errors'
import { getResultsHandler } from '@/tools/experiments/getResults'

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

    // October 2026 traces: 241 rate-limit errors from agents polling results with
    // refresh=true in a tight loop. The 429 message alone says to retry, not that the
    // server recomputes at most once a minute, so agents kept forcing refreshes.
    describe('when a refresh=true poll is rate limited', () => {
        const run = async (refresh: boolean): Promise<Error> => {
            const fetchMock = vi.fn(async (url: string) =>
                url.includes('/experiments/7/')
                    ? new Response(JSON.stringify(experiment), { status: 200 })
                    : new Response(JSON.stringify({ detail: 'Request was throttled.' }), {
                          status: 429,
                          // Over the retry budget, so the client fails fast instead of sleeping.
                          headers: { 'Retry-After': '3600' },
                      })
            )
            vi.stubGlobal('fetch', fetchMock)

            const client = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })
            const context = {
                api: client,
                stateManager: { getProjectId: async () => '42' },
            } as unknown as Parameters<typeof getResultsHandler>[0]

            return (await getResultsHandler(context, { id: 7, refresh }).catch((error: unknown) => error)) as Error
        }

        it('names the one-minute refresh floor next to the retry hint', async () => {
            const error = await run(true)

            expect(error.message).toContain('Retry after 3600 seconds')
            expect(error.message).toContain('at most once a minute')
            expect(error.message).toContain('next_allowed_client_refresh')
            expect(error.message).toContain('without refresh')
        })

        // handleToolError returns the inner recoverable error's message, not the
        // wrapper's, so the hint must survive that unwrap to reach the agent.
        it('carries the hint through to the agent-facing tool error', async () => {
            const error = await run(true)

            const toolResult = handleToolError(error, 'experiment-results-get', undefined, undefined, true)
            const text = (toolResult.content[0] as { text: string }).text
            expect(toolResult.isError).toBe(true)
            expect(text).toContain('Retry after 3600')
            expect(text).toContain('next_allowed_client_refresh')
            expect(text).toContain('without refresh')
        })

        it('leaves the plain 429 message alone when refresh was not forced', async () => {
            const error = await run(false)

            expect(error.message).toContain('rate limit exceeded (429)')
            expect(error.message).not.toContain('next_allowed_client_refresh')
        })
    })
})
