import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import type { ProjectScope } from '@/api/reports'

import { useExperimentsList } from './hooks'

let mockScope: ProjectScope = { host: 'https://app.example.com', projectId: 2 }
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
jest.mock('@/features/views/useViewsAccess', () => ({
    reportScopeError: jest.fn(),
    useFeatureAccess: () => ({ state: 'ok', missingScope: null }),
}))

function response(body: unknown, status = 200): Response {
    return { ok: status < 400, status, headers: new Headers(), text: async () => JSON.stringify(body) } as Response
}

function item(id: number, name: string, startDate: string): Record<string, unknown> {
    return { id, name, feature_flag_key: `flag-${id}`, status: 'running', start_date: startDate, created_at: startDate }
}

const DETAIL = {
    metrics: [{ uuid: 'm1', name: 'Checkout', metric_type: 'funnel', goal: 'increase' }],
    saved_metrics: [],
    status: 'running',
    start_date: '2026-10-01T00:00:00Z',
}

const SIGNIFICANT = {
    id: 'run-1',
    status: 'completed',
    query_to: '2026-11-04T02:00:00Z',
    results: [
        {
            metric_uuid: 'm1',
            status: 'completed',
            result: {
                baseline: { key: 'control', number_of_samples: 1000, sum: 100, sum_squares: 100 },
                variant_results: [
                    {
                        key: 'test',
                        number_of_samples: 1000,
                        sum: 130,
                        sum_squares: 130,
                        method: 'bayesian',
                        credible_interval: [0.1, 0.5],
                        chance_to_win: 0.999,
                        significant: true,
                    },
                ],
            },
        },
    ],
} as const

function wrapper(): ({ children }: { children: ReactNode }) => ReactElement {
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retryDelay: 0 } } })
    return ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
    mockScope = { host: 'https://app.example.com', projectId: 2 }
    setAuthProvider({
        getAuth: () => ({ ...mockScope, accessToken: 'fake-token', session: 1 }),
        refreshAccessToken: async () => null,
    })
})
afterEach(() => {
    setAuthProvider(null)
})

test.each(['bayesian', 'frequentist'] as const)(
    'keeps settled %s decisions first after scrolling, within one project',
    async (method) => {
        let inFlight = 0
        let maxInFlight = 0
        globalThis.fetch = jest.fn(async (url: string) => {
            const { pathname, searchParams } = new URL(url)
            if (pathname.endsWith('/experiments/')) {
                const results =
                    searchParams.get('status') === 'running'
                        ? [
                              item(1, 'Newest', '2026-11-01T00:00:00Z'),
                              item(2, 'Older winner', '2026-10-01T00:00:00Z'),
                              item(3, 'Oldest', '2026-09-01T00:00:00Z'),
                          ]
                        : []
                return response({ results, next: null })
            }
            inFlight += 1
            maxInFlight = Math.max(maxInFlight, inFlight)
            await new Promise((resolve) => setTimeout(resolve, 5))
            inFlight -= 1
            const id = /experiments\/(\d+)\//.exec(pathname)?.[1]
            if (pathname.endsWith('/metrics_recalculation/latest/')) {
                const variant = SIGNIFICANT.results[0].result.variant_results[0]
                const significant = {
                    ...SIGNIFICANT,
                    results: [
                        {
                            ...SIGNIFICANT.results[0],
                            result: {
                                ...SIGNIFICANT.results[0].result,
                                variant_results: [
                                    { ...variant, method, p_value: method === 'frequentist' ? 0.01 : undefined },
                                ],
                            },
                        },
                    ],
                }
                return id === '2' && pathname.startsWith('/api/projects/2/')
                    ? response(significant)
                    : response({ detail: 'No completed recalculation found' }, 404)
            }
            return response({ ...DETAIL, id: Number(id) })
        }) as typeof fetch

        const { result, rerender, unmount } = renderHook(
            ({ visibleIds }: { visibleIds: string[] }) => useExperimentsList('running', '', visibleIds),
            {
                wrapper: wrapper(),
                initialProps: { visibleIds: ['1', '2', '3'] },
            }
        )
        try {
            await waitFor(() => expect(result.current.rowsSettled).toBe(true))
            await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['2', '1', '3']))
            expect(maxInFlight).toBeLessThanOrEqual(2)
            expect(result.current.data?.[0]?.headline).toMatchObject({ kind: 'significant', leader: 'test' })
            expect(result.current.data?.[1]?.headline).toMatchObject({ kind: 'not_yet' })
            expect(result.current.data?.[0]?.method).toBe(method === 'frequentist' ? 'freq' : 'bayes')

            act(() => rerender({ visibleIds: ['1'] }))
            expect(result.current.data?.map((row) => row.id)).toEqual(['2', '1', '3'])
            expect(result.current.data?.[0]?.headline).toMatchObject({ kind: 'significant' })
            expect(result.current.data?.[0]?.method).toBe(method === 'frequentist' ? 'freq' : 'bayes')

            act(() => {
                mockScope = { ...mockScope, projectId: 3 }
                rerender({ visibleIds: ['1', '2', '3'] })
            })
            await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['1', '2', '3']))
            await waitFor(() => expect(result.current.data?.[1]?.headline).toMatchObject({ kind: 'not_yet' }))
        } finally {
            unmount()
        }
    }
)

test('asks the server to search only when the loaded pages do not hold the segment', async () => {
    const searches: (string | null)[] = []
    globalThis.fetch = jest.fn(async (url: string) => {
        const { searchParams } = new URL(url)
        if (searchParams.get('status') === 'draft') {
            searches.push(searchParams.get('search'))
            const search = searchParams.get('search')
            const results = search
                ? [item(9, 'Annual toggle', '2026-10-01T00:00:00Z')]
                : [item(8, 'Pricing copy', '2026-10-02T00:00:00Z')]
            return response({ results, next: search ? null : 'more' })
        }
        return response({ results: [], next: null })
    }) as typeof fetch

    const { result, rerender, unmount } = renderHook(
        ({ search }: { search: string }) => useExperimentsList('draft', search),
        { wrapper: wrapper(), initialProps: { search: '' } }
    )
    try {
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['8']))
        act(() => rerender({ search: 'annual' }))
        expect(result.current.data).toEqual([])
        expect(result.current.searching).toBe(true)
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['9']))
        expect(searches).toEqual([null, 'annual'])
    } finally {
        unmount()
    }
})

test.each(['refetch', 'onPull'] as const)('exposes a failed server search and retries it with %s', async (retry) => {
    let failSearch = true
    const searches: (string | null)[] = []
    globalThis.fetch = jest.fn(async (url: string) => {
        const { searchParams } = new URL(url)
        const search = searchParams.get('search')
        searches.push(search)
        if (search && failSearch) {
            return response({ detail: 'Search unavailable' }, 503)
        }
        return response({
            results: [item(search ? 9 : 8, search ? 'Annual toggle' : 'Pricing copy', '2026-10-01T00:00:00Z')],
            next: search ? null : 'more',
        })
    }) as typeof fetch

    const { result, rerender, unmount } = renderHook(
        ({ search }: { search: string }) => useExperimentsList('draft', search),
        { wrapper: wrapper(), initialProps: { search: '' } }
    )
    try {
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['8']))
        act(() => rerender({ search: 'annual' }))
        await waitFor(() => expect(result.current.searching).toBe(false))
        expect(result.current.isError).toBe(true)
        expect(result.current.error?.message).toContain('Search unavailable')

        failSearch = false
        await act(async () => {
            await result.current[retry]()
        })
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['9']))
        expect(result.current.isError).toBe(false)
        expect(searches.filter((search) => search === null)).toHaveLength(1)
    } finally {
        unmount()
    }
})

test('a pull reads a row again after its detail read failed', async () => {
    let detailReads = 0
    globalThis.fetch = jest.fn(async (url: string) => {
        const { pathname, searchParams } = new URL(url)
        if (pathname === '/api/projects/2/experiments/') {
            const results = searchParams.get('status') === 'running' ? [item(2, 'Winner', '2026-10-01T00:00:00Z')] : []
            return response({ results, next: null })
        }
        if (pathname.endsWith('/metrics_recalculation/latest/')) {
            return response(SIGNIFICANT)
        }
        detailReads += 1
        return detailReads === 1 ? response({ detail: 'Unavailable' }, 503) : response({ ...DETAIL, id: 2 })
    }) as typeof fetch

    const { result, unmount } = renderHook(() => useExperimentsList('running', '', ['2']), { wrapper: wrapper() })
    try {
        await waitFor(() => expect(result.current.data?.[0]?.headline).toBe('error'))
        await act(() => result.current.onPull())
        await waitFor(() => expect(result.current.data?.[0]?.headline).toMatchObject({ kind: 'significant' }))
    } finally {
        unmount()
    }
})
