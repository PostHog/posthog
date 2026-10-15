import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import { queryClient as appQueryClient } from '@/api/queryClient'
import { reportFixture } from '@/model/adapters/testFixtures'
import type { QueryState, ReportView } from '@/model/types'

import { useReport } from './hooks'
import { reportArtefactsQuery, reportDetailQuery, reportPageQuery, reportSignalsQuery } from './queries'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))

const SCOPE = { host: 'https://app.example.com', projectId: 2 }
const REPORT_ID = 'report-1'

describe('useReport', () => {
    beforeEach(() => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2 }),
            refreshAccessToken: async () => null,
        })
        // Refetches never answer, so the screen stays on the cached report while they are in flight.
        globalThis.fetch = jest.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('shows a prefetched report on the first render and refetches it', async () => {
        // The app's stale time keeps the seeded entries fresh, as a prefetch leaves them. Without gc timers Jest can exit.
        const queryClient = new QueryClient({
            defaultOptions: { queries: { ...appQueryClient.getDefaultOptions().queries, gcTime: Infinity } },
        })
        queryClient.setQueryData(reportDetailQuery(SCOPE, REPORT_ID).queryKey, reportFixture({ id: REPORT_ID }))
        queryClient.setQueryData(reportArtefactsQuery(SCOPE, REPORT_ID).queryKey, {
            count: 0,
            next: null,
            results: [],
        })
        queryClient.setQueryData(reportPageQuery(SCOPE, REPORT_ID).queryKey, {
            lead: '',
            impact_sentence: '',
            evidence: [],
            impact_numbers: [],
            last_seen: null,
        })
        queryClient.setQueryData(reportSignalsQuery(SCOPE, REPORT_ID).queryKey, { signals: [] })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const renders: QueryState<ReportView>[] = []
        const { result } = renderHook(
            () => {
                const state = useReport(REPORT_ID)
                renders.push(state)
                return state
            },
            { wrapper }
        )
        await act(async () => undefined)

        expect(renders[0]?.data).toBeDefined()
        expect(globalThis.fetch).toHaveBeenCalledWith(
            `https://app.example.com/api/projects/2/signals/reports/${REPORT_ID}/`,
            expect.anything()
        )
        expect(result.current.isRefetching).toBe(true)
    })

    test.each([200, 500])(
        'keeps the report visible while refreshing missing evidence (signals %s)',
        async (signalsStatus) => {
            jest.useFakeTimers()
            let refreshing = false
            let failRefresh = false
            const pending: { evidence: boolean; resolve: () => void }[] = []
            globalThis.fetch = jest.fn(async (input) => {
                const url = String(input)
                const page = url.endsWith('/page/')
                const signals = url.endsWith('/signals/')
                if (refreshing) {
                    await new Promise<void>((resolve) => pending.push({ evidence: page || signals, resolve }))
                }
                const status = page ? 404 : signals ? signalsStatus : failRefresh ? 503 : 200
                const body = url.includes('/artefacts/')
                    ? { count: 0, next: null, results: [] }
                    : signals
                      ? { signals: [] }
                      : reportFixture({ id: REPORT_ID })
                return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
            }) as typeof fetch
            const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            )
            const renders: QueryState<ReportView>[] = []
            const { result, unmount } = renderHook(
                () => {
                    const state = useReport(REPORT_ID)
                    renders.push(state)
                    return state
                },
                { wrapper }
            )
            try {
                expect(result.current.isLoading).toBe(true)
                await act(async () => {
                    await jest.advanceTimersByTimeAsync(10)
                })
                expect(result.current.data?.id).toBe(REPORT_ID)
                renders.length = 0
                refreshing = true
                await act(async () => {
                    void result.current.refetch()
                    await jest.advanceTimersByTimeAsync(10)
                })
                expect(result.current.data?.id).toBe(REPORT_ID)
                expect(result.current.isRefetching).toBe(true)
                expect(renders.every((state) => state.data?.id === REPORT_ID && !state.isLoading)).toBe(true)
                // Failed background requests must also leave the last report readable and stop the indicator.
                failRefresh = true
                await act(async () => {
                    for (const request of pending.filter((request) => !request.evidence)) {
                        request.resolve()
                    }
                    await jest.advanceTimersByTimeAsync(10)
                })
                expect(result.current.data?.id).toBe(REPORT_ID)
                expect(result.current.isRefetching).toBe(true)
                await act(async () => {
                    for (const request of pending.filter((request) => request.evidence)) {
                        request.resolve()
                    }
                    await jest.advanceTimersByTimeAsync(10)
                })
                expect(result.current.isRefetching).toBe(false)
                expect(renders.every((state) => state.data?.id === REPORT_ID && !state.isLoading)).toBe(true)
            } finally {
                unmount()
                client.clear()
                jest.useRealTimers()
            }
        }
    )
})
