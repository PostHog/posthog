import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState, type AppStateStatus } from 'react-native'
import { setAuthProvider } from '@/api/client'
import { INBOX_PAGE_SIZE, postReadStates, reportKeys } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { type DataMode, useDemoMode } from '@/demo/demoMode'
import { reportFixture } from '@/model/adapters/testFixtures'

import { useInboxItems, useMarkReadOnOpen, useSetReportRead } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
let mockDataMode: DataMode = 'live'
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => mockDataMode,
}))

function scopeOf(): { host: string; projectId: number } {
    return { host: 'https://app.example.com', projectId: 2 }
}

function jsonResponse(body: unknown, status = 200): Response {
    return {
        ok: status < 400,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('inbox hooks', () => {
    const posted: unknown[] = []

    beforeEach(() => {
        posted.length = 0
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: () => undefined })
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        // Read posts never answer, so the first one is still in flight when the next report opens.
        globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
            posted.push(JSON.parse(String(init.body)))
            return new Promise<Response>(() => undefined)
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
        jest.restoreAllMocks()
    })

    test('marks each report read on a fast Prev/Next', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { rerender } = renderHook(({ id }: { id: string }) => useMarkReadOnOpen(id), {
            initialProps: { id: 'report-1' },
            wrapper,
        })
        rerender({ id: 'report-2' })
        await act(async () => undefined)

        expect(posted).toEqual([
            { report_ids: ['report-1'], read: true },
            { report_ids: ['report-2'], read: true },
        ])
    })

    test('does not mark an unloaded report read', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        renderHook(() => useMarkReadOnOpen(undefined), { wrapper })
        await act(async () => undefined)
        expect(posted).toEqual([])
    })

    test.each([true, false])(
        'restores the previous state after a failed write to %s and permits a retry',
        async (read) => {
            const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
            const scope = { host: 'https://app.example.com', projectId: 2 }
            const key = reportKeys.readStates(scope, ['report-1'])
            queryClient.setQueryData(key, { 'report-1': !read })
            let rejectWrite: (error: Error) => void = () => undefined
            globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
                posted.push(JSON.parse(String(init.body)))
                return new Promise<Response>((_resolve, reject) => {
                    rejectWrite = reject
                })
            }) as unknown as typeof fetch
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
            )
            const { result } = renderHook(() => useSetReportRead(), { wrapper })
            const failed = result.current('report-1', read).catch((error: Error) => error)
            await waitFor(() => expect(queryClient.getQueryData(key)).toEqual({ 'report-1': read }))
            await act(async () => rejectWrite(new Error('offline')))
            await expect(failed).resolves.toBeInstanceOf(Error)
            expect(queryClient.getQueryData(key)).toEqual({ 'report-1': !read })
            void result.current('report-1', read).catch(() => undefined)
            await waitFor(() => expect(posted).toHaveLength(2))
            expect(posted).toEqual([
                { report_ids: ['report-1'], read },
                { report_ids: ['report-1'], read },
            ])
        }
    )

    test('shows a report unread at once while the unread write is in flight', async () => {
        globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
            if (new URL(url).pathname.endsWith('/read_state/')) {
                const body = JSON.parse(String(init?.body))
                if ('read' in body) {
                    posted.push(body)
                    return new Promise<Response>(() => undefined)
                }
                return jsonResponse({ states: { r1: true } })
            }
            return jsonResponse({ count: 1, next: null, results: [reportFixture({ id: 'r1' })] })
        }) as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(() => ({ inbox: useInboxItems(), setRead: useSetReportRead() }), { wrapper })
        try {
            await waitFor(() => expect(screen.result.current.inbox.data?.[0]?.read).toBe(true))
            void screen.result.current.setRead('r1', false).catch(() => undefined)
            await waitFor(() => expect(screen.result.current.inbox.data?.[0]?.read).toBe(false))
            expect(posted).toEqual([{ report_ids: ['r1'], read: false }])
            await act(async () => {
                await queryClient.refetchQueries({ queryKey: reportKeys.readStatesAll(scopeOf()) })
            })
            expect(screen.result.current.inbox.data?.[0]?.read).toBe(false)
        } finally {
            screen.unmount()
            queryClient.clear()
        }
    })

    test.each([
        { first: 'succeeds', second: 'succeeds', shown: false },
        { first: 'succeeds', second: 'fails', shown: true },
        { first: 'fails', second: 'fails', shown: false },
    ] as const)(
        'sends read then unread in order when the first $first and the second $second',
        async ({ first, second, shown }) => {
            const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
            const key = reportKeys.readStates(scopeOf(), ['report-1'])
            queryClient.setQueryData(key, { 'report-1': false })
            const writes: { resolve: (response: Response) => void; reject: (error: Error) => void }[] = []
            globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
                posted.push(JSON.parse(String(init.body)))
                return new Promise<Response>((resolve, reject) => {
                    writes.push({ resolve, reject })
                })
            }) as unknown as typeof fetch
            const finish = (index: number, outcome: 'succeeds' | 'fails'): void => {
                if (outcome === 'succeeds') writes[index]?.resolve(jsonResponse({ states: {} }))
                else writes[index]?.reject(new Error('offline'))
            }
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
            )
            const { result } = renderHook(() => useSetReportRead(), { wrapper })
            const markedRead = result.current('report-1', true).catch(() => undefined)
            const markedUnread = result.current('report-1', false).catch(() => undefined)
            await waitFor(() => expect(posted).toHaveLength(1))
            await waitFor(() => expect(queryClient.getQueryData(key)).toEqual({ 'report-1': false }))
            await act(async () => finish(0, first))
            await waitFor(() => expect(posted).toHaveLength(2))
            expect(queryClient.getQueryData(key)).toEqual({ 'report-1': false })
            await act(async () => {
                finish(1, second)
                await Promise.all([markedRead, markedUnread])
            })
            expect(posted).toEqual([
                { report_ids: ['report-1'], read: true },
                { report_ids: ['report-1'], read: false },
            ])
            expect(queryClient.getQueryData(key)).toEqual({ 'report-1': shown })
        }
    )

    test('marks a demo report unread after it was read', async () => {
        mockDataMode = 'demo'
        useDemoMode.getState().setEnabled(true)
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(() => ({ inbox: useInboxItems(), setRead: useSetReportRead() }), { wrapper })
        try {
            const reportId = screen.result.current.inbox.data?.[0]?.reportId as string
            await act(() => screen.result.current.setRead(reportId, true))
            expect(screen.result.current.inbox.data?.[0]?.read).toBe(true)
            await act(() => screen.result.current.setRead(reportId, false))
            expect(screen.result.current.inbox.data?.[0]?.read).toBe(false)
            expect(posted).toEqual([])
        } finally {
            screen.unmount()
            useDemoMode.getState().setEnabled(false)
            mockDataMode = 'live'
        }
    })

    test('shows unread only after a fresh successful answer and hides it after a failed refresh', async () => {
        let answerRead: ((response: Response) => void) | undefined
        globalThis.fetch = jest.fn(async (url: string) => {
            if (new URL(url).pathname.endsWith('/read_state/'))
                return new Promise<Response>((resolve) => {
                    answerRead = resolve
                })
            return jsonResponse({ count: 1, next: null, results: [reportFixture({ id: 'r1' })] })
        }) as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const scope = { host: 'https://app.example.com', projectId: 2 }
        const key = reportKeys.readStates(scope, ['r1'])
        queryClient.setQueryData(key, { r1: false })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(() => useInboxItems(), { wrapper })
        await waitFor(() => expect(screen.result.current.data?.[0]?.read).toBe(true))
        await waitFor(() => expect(answerRead).toBeDefined())
        await act(async () => answerRead?.(jsonResponse({ states: { r1: false } })))
        await waitFor(() => expect(screen.result.current.data?.[0]?.read).toBe(false))
        globalThis.fetch = jest.fn(async () => jsonResponse({}, 404)) as typeof fetch
        await act(async () => {
            await queryClient.refetchQueries({ queryKey: key })
        })
        await waitFor(() => expect(screen.result.current.data?.[0]?.read).toBe(true))
    })

    test('polls every thirty seconds only while focused and foregrounded', async () => {
        jest.useFakeTimers()
        const previousState = AppState.currentState
        AppState.currentState = 'active'
        let appChange: ((state: AppStateStatus) => void) | undefined
        const listener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
            appChange = handler
            return { remove: () => undefined }
        })
        let reads = 0
        globalThis.fetch = jest.fn(async (url: string) => {
            if (new URL(url).pathname.endsWith('/read_state/')) {
                reads += 1
                return jsonResponse({ states: { r1: false } })
            }
            return jsonResponse({ count: 1, next: null, results: [reportFixture({ id: 'r1' })] })
        }) as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(
            ({ focused }: { focused: boolean }) => useInboxItems({ refreshWhileVisible: focused }),
            {
                initialProps: { focused: true },
                wrapper,
            }
        )
        try {
            await waitFor(() => expect(screen.result.current.data?.[0]?.read).toBe(false))
            const initial = reads
            await act(async () => {
                await jest.advanceTimersByTimeAsync(30_000)
            })
            expect(reads).toBe(initial + 1)
            screen.rerender({ focused: false })
            await act(async () => {
                await jest.advanceTimersByTimeAsync(30_000)
            })
            expect(reads).toBe(initial + 1)
            screen.rerender({ focused: true })
            await waitFor(() => expect(reads).toBe(initial + 2))
            act(() => appChange?.('background'))
            await act(async () => {
                await jest.advanceTimersByTimeAsync(30_000)
            })
            expect(reads).toBe(initial + 2)
            act(() => appChange?.('active'))
            await waitFor(() => expect(reads).toBe(initial + 3))
        } finally {
            screen.unmount()
            queryClient.clear()
            listener.mockRestore()
            AppState.currentState = previousState
            jest.useRealTimers()
        }
    })

    test('ignores a read write that completes after switching project', async () => {
        const originalProject = useAuthStore.getState().projectId
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const key = reportKeys.readStates({ host: 'https://app.example.com', projectId: 2 }, ['report-1'])
        queryClient.setQueryData(key, { 'report-1': false })
        let finish: ((response: Response) => void) | undefined
        globalThis.fetch = jest.fn(
            () =>
                new Promise<Response>((resolve) => {
                    finish = resolve
                })
        ) as typeof fetch
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(() => useMarkReadOnOpen('report-1'), { wrapper })
        try {
            await waitFor(() => expect(finish).toBeDefined())
            act(() => {
                useAuthStore.setState({ projectId: 9 })
                queryClient.setQueryData(key, { 'report-1': false })
            })
            await act(async () => finish?.(jsonResponse({ states: { 'report-1': true } })))
            expect(queryClient.getQueryData(key)).toEqual({ 'report-1': false })
        } finally {
            screen.unmount()
            useAuthStore.setState({ projectId: originalProject })
            queryClient.clear()
        }
    })

    test('cancels an older read fetch and deduplicates simultaneous opens', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const key = reportKeys.readStates({ host: 'https://app.example.com', projectId: 2 }, ['report-1'])
        queryClient.setQueryData(key, { 'report-1': false })
        let finishPoll: ((response: Response) => void) | undefined
        let finishWrite: ((response: Response) => void) | undefined
        let pollSignal: AbortSignal | undefined
        let writes = 0
        globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
            const write = JSON.parse(String(init.body)).read === true
            if (write) writes += 1
            else pollSignal = init.signal as AbortSignal
            return new Promise<Response>((resolve) => {
                if (write) finishWrite = resolve
                else finishPoll = resolve
            })
        }) as typeof fetch
        const polling = queryClient
            .fetchQuery({
                queryKey: key,
                queryFn: async ({ signal }) => (await postReadStates(['report-1'], undefined, signal)).states,
            })
            .catch(() => undefined)
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const screen = renderHook(
            () => {
                useMarkReadOnOpen('report-1')
                useMarkReadOnOpen('report-1')
            },
            { wrapper }
        )
        try {
            await waitFor(() => expect(writes).toBe(1))
            expect(pollSignal?.aborted).toBe(true)
            await act(async () => {
                finishPoll?.(jsonResponse({ states: { 'report-1': false } }))
                finishWrite?.(jsonResponse({ states: { 'report-1': true } }))
                await polling
            })
            expect(queryClient.getQueryData(key)).toEqual({ 'report-1': true })
        } finally {
            screen.unmount()
            queryClient.clear()
        }
    })

    test('pages through the ranking, retrying a failed page only when asked, reading states once per page', async () => {
        const offsets: string[] = []
        const readStateBatches: string[][] = []
        const firstPage = Array.from({ length: INBOX_PAGE_SIZE }, (_, index) => reportFixture({ id: `r${index}` }))
        let secondPageFailures = 1
        globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
            const { pathname, searchParams } = new URL(url)
            if (pathname.endsWith('/read_state/')) {
                readStateBatches.push(JSON.parse(String(init?.body)).report_ids)
                return jsonResponse({ states: {} })
            }
            const offset = searchParams.get('offset') ?? ''
            offsets.push(offset)
            if (offset !== '0' && secondPageFailures > 0) {
                secondPageFailures -= 1
                return jsonResponse({ detail: 'Server error' }, 500)
            }
            return jsonResponse(
                offset === '0'
                    ? { count: INBOX_PAGE_SIZE + 1, next: 'https://app.example.com/next', results: firstPage }
                    : { count: INBOX_PAGE_SIZE + 1, next: null, results: [reportFixture({ id: 'last' })] }
            )
        }) as unknown as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { result } = renderHook(() => useInboxItems(), { wrapper })

        await waitFor(() => expect(result.current.data).toHaveLength(INBOX_PAGE_SIZE))
        expect(result.current.hasMore).toBe(true)
        act(() => result.current.loadMore())
        await waitFor(() => expect(result.current.loadMoreFailed).toBe(true))
        // The list calls this again when the error footer replaces the spinner.
        act(() => result.current.loadMore())
        expect(result.current.isLoadingMore).toBe(false)
        act(() => result.current.retryLoadMore())
        await waitFor(() => expect(result.current.data).toHaveLength(INBOX_PAGE_SIZE + 1))
        await waitFor(() => expect(readStateBatches).toHaveLength(2))

        expect(result.current.hasMore).toBe(false)
        expect(offsets).toEqual(['0', String(INBOX_PAGE_SIZE), String(INBOX_PAGE_SIZE)])
        expect(readStateBatches.map((ids) => ids.length)).toEqual([INBOX_PAGE_SIZE, 1])
    })

    test('loads every page by itself for a sort and orders the items across pages', async () => {
        const offsets: string[] = []
        const firstPage = Array.from({ length: INBOX_PAGE_SIZE }, (_, index) =>
            reportFixture({ id: `r${index}`, created_at: new Date(Date.UTC(2026, 9, 1, index)).toISOString() })
        )
        globalThis.fetch = jest.fn(async (url: string) => {
            const { pathname, searchParams } = new URL(url)
            if (pathname.endsWith('/read_state/')) {
                return jsonResponse({ states: {} })
            }
            const offset = searchParams.get('offset') ?? ''
            offsets.push(offset)
            return jsonResponse(
                offset === '0'
                    ? { count: INBOX_PAGE_SIZE + 1, next: 'https://app.example.com/next', results: firstPage }
                    : {
                          count: INBOX_PAGE_SIZE + 1,
                          next: null,
                          results: [reportFixture({ id: 'last', created_at: '2026-10-02T00:00:00Z' })],
                      }
            )
        }) as unknown as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { result } = renderHook(
            () => useInboxItems({ filters: { sort: 'newest', createdWindow: 'any', sources: [] } }),
            { wrapper }
        )

        await waitFor(() => expect(result.current.data).toHaveLength(INBOX_PAGE_SIZE + 1))
        expect(offsets).toEqual(['0', String(INBOX_PAGE_SIZE)])
        expect(result.current.isLoadingMore).toBe(false)
        expect(result.current.data?.map((item) => item.id).slice(0, 3)).toEqual(['last', 'r19', 'r18'])
        expect(result.current.data?.at(-1)?.id).toBe('r0')
    })
})
