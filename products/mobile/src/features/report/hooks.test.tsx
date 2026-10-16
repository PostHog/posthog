import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { setAuthProvider } from '@/api/client'
import { queryClient as appQueryClient } from '@/api/queryClient'
import { useHandoffStore } from '@/features/handoff/handoffStore'
import { useReportWithLiveRun } from '@/features/handoff/useReportWithLiveRun'
import { reportFixture } from '@/model/adapters/testFixtures'
import type { QueryState, ReportView } from '@/model/types'

import { REPORT_POLL_INTERVAL_MS, useReport } from './hooks'
import { reportArtefactsQuery, reportDetailQuery, reportPageQuery, reportSignalsQuery } from './queries'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('expo-router', () => ({
    useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]),
}))
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
        AppState.currentState = 'active'
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: () => undefined })
        useHandoffStore.setState({ reports: {} })
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        // Refetches never answer, so the screen stays on the cached report while they are in flight.
        globalThis.fetch = jest.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
        jest.restoreAllMocks()
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

    test('polls only the visible foreground report and refreshes on return without polling evidence', async () => {
        jest.useFakeTimers()
        let appChange!: (state: AppStateStatus) => void
        const listener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
            appChange = handler
            return { remove: () => undefined }
        })
        const data = reportFixture({ id: REPORT_ID })
        globalThis.fetch = jest.fn(async (input) => {
            const url = String(input)
            const body = url.includes('/artefacts/')
                ? { count: 0, next: null, results: [] }
                : url.includes('/signals/') && url.endsWith('/signals/')
                  ? { signals: [] }
                  : url.includes('/page/')
                    ? { lead: '', evidence: [], impact_sentence: '', impact_numbers: [], last_seen: null }
                    : data
            return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }) as typeof fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const { result, rerender, unmount } = renderHook<QueryState<ReportView>, { visible: boolean }>(
            ({ visible }) => useReport(REPORT_ID, true, visible),
            {
                wrapper,
                initialProps: { visible: true },
            }
        )
        const count = (path: string): number =>
            jest.mocked(globalThis.fetch).mock.calls.filter(([url]) => String(url).endsWith(path)).length
        try {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(result.current.data).toBeDefined()
            const evidenceCalls = count('/page/') + count('/signals/')
            const first = count(`/${REPORT_ID}/`)
            await act(async () => {
                await jest.advanceTimersByTimeAsync(REPORT_POLL_INTERVAL_MS)
            })
            expect(count(`/${REPORT_ID}/`)).toBe(first + 1)
            expect(count('/page/') + count('/signals/')).toBe(evidenceCalls)
            await act(async () => {
                appChange('background')
            })
            const beforeBackground = jest.mocked(globalThis.fetch).mock.calls.length
            await act(async () => {
                await jest.advanceTimersByTimeAsync(REPORT_POLL_INTERVAL_MS * 3)
            })
            expect(jest.mocked(globalThis.fetch).mock.calls).toHaveLength(beforeBackground)
            expect(result.current.data).toBeDefined()
            await act(async () => {
                appChange('active')
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(count(`/${REPORT_ID}/`)).toBeGreaterThan(first + 1)
            rerender({ visible: false })
            const beforeCovered = jest.mocked(globalThis.fetch).mock.calls.length
            await act(async () => {
                await jest.advanceTimersByTimeAsync(REPORT_POLL_INTERVAL_MS * 3)
            })
            expect(jest.mocked(globalThis.fetch).mock.calls).toHaveLength(beforeCovered)
        } finally {
            unmount()
            client.clear()
            listener.mockRestore()
            jest.useRealTimers()
        }
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

    test('refreshes on PR and turn changes with a throttle, without refetching for message chunks', async () => {
        jest.useFakeTimers()
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        client.setQueryData(reportDetailQuery(SCOPE, REPORT_ID).queryKey, reportFixture({ id: REPORT_ID }))
        client.setQueryData(reportArtefactsQuery(SCOPE, REPORT_ID).queryKey, { count: 0, next: null, results: [] })
        client.setQueryData(reportPageQuery(SCOPE, REPORT_ID).queryKey, {
            lead: '',
            evidence: [],
            impact_sentence: '',
            impact_numbers: [],
            last_seen: null,
        })
        client.setQueryData(reportSignalsQuery(SCOPE, REPORT_ID).queryKey, { signals: [] })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const { unmount } = renderHook(() => useReportWithLiveRun(REPORT_ID), { wrapper })
        const notification = (method: string, params: unknown): unknown => ({
            type: 'notification',
            notification: { method, params },
        })
        const context = { source: 'live' as const, sourceRunId: 'refresh-run' }
        try {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(10)
            })
            await act(async () => {
                useHandoffStore.getState().applySnapshot(REPORT_ID, 'refresh-task', {
                    id: 'refresh-run',
                    task: 'refresh-task',
                    status: 'in_progress',
                    stage: null,
                    branch: null,
                    error_message: null,
                    output: null,
                    completed_at: null,
                })
                await jest.advanceTimersByTimeAsync(10)
            })
            const afterSnapshot = jest.mocked(globalThis.fetch).mock.calls.length
            await act(async () => {
                for (let i = 0; i < 20; i++) {
                    useHandoffStore.getState().applyFrame(
                        REPORT_ID,
                        'refresh-run',
                        notification('session/update', {
                            update: { sessionUpdate: 'agent_message_chunk', content: { text: 'hello' } },
                        }),
                        context
                    )
                }
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(jest.mocked(globalThis.fetch).mock.calls).toHaveLength(afterSnapshot)
            await act(async () => {
                useHandoffStore.getState().applyFrame(
                    REPORT_ID,
                    'refresh-run',
                    {
                        type: 'task_run_state',
                        run_id: 'refresh-run',
                        output: { pr_url: 'https://github.com/example/repo/pull/4' },
                    },
                    context
                )
                useHandoffStore
                    .getState()
                    .applyFrame(REPORT_ID, 'refresh-run', notification('_posthog/turn_complete', {}), context)
                await jest.advanceTimersByTimeAsync(1000)
            })
            expect(jest.mocked(globalThis.fetch).mock.calls).toHaveLength(afterSnapshot)
            await act(async () => {
                await jest.advanceTimersByTimeAsync(1000)
            })
            expect(jest.mocked(globalThis.fetch).mock.calls).toHaveLength(afterSnapshot + 2)
        } finally {
            unmount()
            client.clear()
            jest.useRealTimers()
        }
    })
})
