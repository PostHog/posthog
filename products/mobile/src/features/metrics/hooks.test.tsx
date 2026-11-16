import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import type { MetricData } from '@/model/types'

import { useMetricAggregate, useMetricSeries } from './hooks'

let mockMode: 'loading' | 'demo' | 'live' = 'live'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => mockMode }))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})

const QUERY: MetricData = {
    kind: 'query',
    seriesQuery: { kind: 'TrendsQuery', interval: 'week', trendsFilter: { display: 'ActionsBar' } },
    aggregateQuery: { kind: 'TrendsQuery', interval: 'week', trendsFilter: { display: 'BoldNumber' } },
}

const STATIC: MetricData = {
    kind: 'static',
    series: { interval: 'day', points: [{ at: '2026-10-13', value: 5 }] },
    value: 5,
}

let client = new QueryClient()

function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('metric hooks', () => {
    const posted: unknown[] = []

    beforeEach(() => {
        mockMode = 'live'
        posted.length = 0
        // No garbage collection timer, so Jest can exit once the tests finish.
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (_url: string, init: RequestInit) => {
            const { query } = JSON.parse(String(init.body)) as { query: { trendsFilter: { display: string } } }
            posted.push(query.trendsFilter.display)
            return {
                ok: true,
                status: 200,
                headers: { get: () => null },
                text: async () =>
                    JSON.stringify({
                        results: [{ days: ['2026-10-05', '2026-10-12'], data: [3, 4], aggregated_value: 6 }],
                    }),
            } as unknown as Response
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        client.clear()
        setAuthProvider(null)
    })

    test.each<[string, MetricData | undefined, 'loading' | 'demo' | 'live']>([
        ['static data', STATIC, 'live'],
        ['redacted data', { kind: 'none' }, 'live'],
        ['a chart without data', undefined, 'live'],
        ['a query in demo mode', QUERY, 'demo'],
    ])('%s settles at once without a request', (_name, data, mode) => {
        mockMode = mode
        const { result } = renderHook(() => ({ series: useMetricSeries(data), total: useMetricAggregate(data) }), {
            wrapper,
        })

        expect(result.current.series).toMatchObject({ isLoading: false, isError: false })
        expect(result.current.series.data).toEqual(data?.kind === 'static' ? data.series : undefined)
        expect(result.current.total.data).toBe(data?.kind === 'static' ? 5 : undefined)
        expect(posted).toEqual([])
    })

    test('runs the series and aggregate queries and parses each', async () => {
        const { result } = renderHook(() => ({ series: useMetricSeries(QUERY), total: useMetricAggregate(QUERY) }), {
            wrapper,
        })
        expect(result.current.series.isLoading).toBe(true)

        await waitFor(() => expect(result.current.total.data).toBe(6))
        await waitFor(() => expect(result.current.series.data).toBeDefined())
        expect(result.current.series.data).toEqual({
            interval: 'week',
            points: [
                { at: '2026-10-05', value: 3 },
                { at: '2026-10-12', value: 4 },
            ],
        })
        expect([...posted].sort()).toEqual(['ActionsBar', 'BoldNumber'])
    })

    test('a disabled query stays idle', () => {
        const { result } = renderHook(() => useMetricSeries(QUERY, false), { wrapper })

        expect(result.current).toMatchObject({ isLoading: false, isError: false, data: undefined })
        expect(posted).toEqual([])
    })
})
