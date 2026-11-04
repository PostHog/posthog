import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import { getNetworkStateAsync, NetworkStateType } from 'expo-network'
import type { ReactElement, ReactNode } from 'react'
import { AppState, type ViewToken } from 'react-native'
import { setAuthProvider } from '@/api/client'
import { useConnectivity } from '@/lib/connectivity'
import { inboxFromReports } from '@/model/adapters/inbox'
import { reportFixture } from '@/model/adapters/testFixtures'
import type { InboxItem } from '@/model/types'

import { reportDetailQuery } from '../report/queries'
import { usePrefetchReports } from './usePrefetchReports'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
let mockScope = { host: 'https://app.example.com', projectId: 2 }
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))

function response(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

function showRows(props: ReturnType<typeof usePrefetchReports>, first: number, last: number): void {
    props.onViewableItemsChanged({
        viewableItems: [{ index: first }, { index: last }] as ViewToken<InboxItem>[],
        changed: [],
    })
}

function controlledRequests(): {
    fetch: typeof fetch
    pending: { path: string; signal: AbortSignal | null | undefined; resolve: (response: Response) => void }[]
} {
    const pending: { path: string; signal: AbortSignal | null | undefined; resolve: (response: Response) => void }[] =
        []
    const fetcher = jest.fn(
        (url: string, init?: RequestInit) =>
            new Promise<Response>((resolve, reject) => {
                pending.push({ path: new URL(url).pathname + new URL(url).search, signal: init?.signal, resolve })
                init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
            })
    ) as unknown as typeof fetch
    return { fetch: fetcher, pending }
}

describe('usePrefetchReports', () => {
    beforeEach(() => {
        mockScope = { host: 'https://app.example.com', projectId: 2 }
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: jest.fn() })
        setAuthProvider({
            getAuth: () => ({
                host: 'https://app.example.com',
                accessToken: 'fake',
                projectId: mockScope.projectId,
                session: 1,
            }),
            refreshAccessToken: async () => null,
        })
        AppState.currentState = 'active'
        useConnectivity.setState({ status: 'connected', type: NetworkStateType.WIFI })
        jest.mocked(getNetworkStateAsync).mockResolvedValue({ type: NetworkStateType.WIFI, isConnected: true })
    })
    afterEach(() => {
        setAuthProvider(null)
        jest.restoreAllMocks()
    })

    test.each(['focus', 'offline', 'unknown', 'cellular', 'project', 'background', 'unmount'] as const)(
        '%s pauses pending work and cancels only speculative reads',
        async (pause) => {
            const appListeners = new Set<(state: 'active' | 'background') => void>()
            const appListener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
                appListeners.add(listener)
                return { remove: () => appListeners.delete(listener) }
            })
            const requests = controlledRequests()
            globalThis.fetch = requests.fetch
            const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            )
            const items = inboxFromReports(['a', 'b', 'c'].map((id) => reportFixture({ id })))
            const screen = renderHook(({ focused }: { focused: boolean }) => usePrefetchReports(items, focused), {
                initialProps: { focused: true },
                wrapper,
            })
            try {
                act(() => showRows(screen.result.current, 0, 1))
                await waitFor(() => expect(requests.pending).toHaveLength(1))
                await act(async () => {
                    if (pause === 'focus') screen.rerender({ focused: false })
                    else if (pause === 'offline') useConnectivity.setState({ status: 'offline' })
                    else if (pause === 'unknown') useConnectivity.setState({ status: 'unknown' })
                    else if (pause === 'project') {
                        mockScope = { ...mockScope, projectId: 3 }
                        screen.rerender({ focused: true })
                    } else if (pause === 'cellular') useConnectivity.setState({ type: NetworkStateType.CELLULAR })
                    else if (pause === 'background') for (const listener of appListeners) listener('background')
                    else screen.unmount()
                })
                expect(requests.pending[0]?.signal?.aborted).toBe(true)
                expect(requests.pending).toHaveLength(1)
                if (pause !== 'unmount') {
                    await act(async () => {
                        if (pause === 'focus') screen.rerender({ focused: true })
                        else if (pause === 'offline' || pause === 'unknown')
                            useConnectivity.setState({ status: 'connected' })
                        else if (pause === 'project') showRows(screen.result.current, 0, 1)
                        else if (pause === 'cellular') useConnectivity.setState({ type: NetworkStateType.WIFI })
                        else for (const listener of appListeners) listener('active')
                    })
                    await waitFor(() => expect(requests.pending).toHaveLength(2))
                }
            } finally {
                screen.unmount()
                client.clear()
                appListener.mockRestore()
            }
        }
    )

    test('scrolling replaces queued rows and stops subsequent stages for an offscreen report', async () => {
        const requests = controlledRequests()
        globalThis.fetch = requests.fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const items = inboxFromReports(Array.from({ length: 40 }, (_, index) => reportFixture({ id: `r${index}` })))
        const { result, unmount } = renderHook(() => usePrefetchReports(items, true), { wrapper })
        try {
            act(() => showRows(result.current, 10, 10))
            await waitFor(() => expect(requests.pending).toHaveLength(1))
            act(() => showRows(result.current, 20, 20))
            await act(async () => requests.pending[0]?.resolve(response(200, reportFixture({ id: 'r10' }))))
            await waitFor(() => expect(requests.pending).toHaveLength(2))
            expect(requests.pending.map((request) => request.path)).toEqual([
                '/api/projects/2/signals/reports/r10/',
                '/api/projects/2/signals/reports/r20/',
            ])
            await act(async () => requests.pending[1]?.resolve(response(200, reportFixture({ id: 'r20' }))))
            await waitFor(() => expect(requests.pending).toHaveLength(3))
            expect(requests.pending[2]?.path).toContain('/r20/artefacts/')
        } finally {
            unmount()
            client.clear()
        }
    })

    test('opening a prefetched report adopts the shared request and cleanup cannot cancel it', async () => {
        const requests = controlledRequests()
        globalThis.fetch = requests.fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const items = inboxFromReports([reportFixture({ id: 'a' })])
        const { result, unmount } = renderHook(() => usePrefetchReports(items, true), { wrapper })
        let stopObserving = (): void => undefined
        try {
            act(() => showRows(result.current, 0, 0))
            await waitFor(() => expect(requests.pending).toHaveLength(1))
            const observer = new QueryObserver(
                client,
                reportDetailQuery({ host: 'https://app.example.com', projectId: 2 }, 'a')
            )
            await act(async () => {
                stopObserving = observer.subscribe(() => undefined)
            })
            unmount()
            expect(requests.pending[0]?.signal?.aborted).toBe(false)
            await act(async () => requests.pending[0]?.resolve(response(200, reportFixture({ id: 'a' }))))
            await waitFor(() => expect(observer.getCurrentResult().data?.id).toBe('a'))
            expect(requests.pending).toHaveLength(1)
        } finally {
            stopObserving()
            unmount()
            client.clear()
        }
    })

    test.each(['unobserved', 'adopted', 'observer-policy'] as const)(
        'a transient prefetch failure follows the %s retry policy',
        async (mode) => {
            const requests = controlledRequests()
            globalThis.fetch = requests.fetch
            const client = new QueryClient({
                defaultOptions: { queries: { retry: 1, retryDelay: 0, gcTime: Infinity } },
            })
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            )
            const options = reportDetailQuery(mockScope, 'a')
            const items = inboxFromReports([reportFixture({ id: 'a' })])
            const screen = renderHook(() => usePrefetchReports(items, true), { wrapper })
            let stop = (): void => undefined
            const observerPolicy = jest.fn(() => false)
            try {
                act(() => showRows(screen.result.current, 0, 0))
                await waitFor(() => expect(requests.pending).toHaveLength(1))
                const observer = new QueryObserver(client, {
                    ...options,
                    ...(mode === 'observer-policy' ? { retry: observerPolicy } : {}),
                })
                if (mode !== 'unobserved')
                    act(() => {
                        stop = observer.subscribe(() => undefined)
                    })
                const detailPath = requests.pending[0]?.path
                await act(async () => requests.pending[0]?.resolve(response(503, { detail: 'Try again' })))
                if (mode === 'adopted') {
                    await waitFor(() =>
                        expect(requests.pending.filter((request) => request.path === detailPath)).toHaveLength(2)
                    )
                    await act(async () =>
                        requests.pending
                            .find((request, index) => index > 0 && request.path === detailPath)
                            ?.resolve(response(200, reportFixture({ id: 'a' })))
                    )
                    await waitFor(() => expect(observer.getCurrentResult().data?.id).toBe('a'))
                } else {
                    await waitFor(() => expect(client.getQueryState(options.queryKey)?.status).toBe('error'))
                    expect(requests.pending.filter((request) => request.path === detailPath)).toHaveLength(1)
                    if (mode === 'observer-policy') expect(observerPolicy).toHaveBeenCalledWith(0, expect.any(Error))
                }
            } finally {
                stop()
                screen.unmount()
                client.clear()
            }
        }
    )

    test('foreground reads finish before speculation begins', async () => {
        const requests = controlledRequests()
        globalThis.fetch = requests.fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        let finish = (): void => undefined
        const observer = new QueryObserver(client, {
            queryKey: ['foreground'],
            queryFn: () =>
                new Promise<string>((resolve) => {
                    finish = () => resolve('loaded')
                }),
        })
        const stop = observer.subscribe(() => undefined)
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const items = inboxFromReports([reportFixture({ id: 'a' })])
        const { result, unmount } = renderHook(() => usePrefetchReports(items, true), { wrapper })
        try {
            act(() => showRows(result.current, 0, 0))
            expect(requests.pending).toEqual([])
            await act(async () => finish())
            await waitFor(() => expect(requests.pending).toHaveLength(1))
        } finally {
            unmount()
            stop()
            client.clear()
        }
    })

    test('asks once for a Today page the project does not have, not again when the window moves', async () => {
        const paths: string[] = []
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string) => {
            const { pathname } = new URL(url)
            paths.push(pathname)
            if (pathname.includes('/today/')) {
                return response(404, { detail: 'Not found' })
            }
            if (pathname.endsWith('/artefacts/')) {
                return response(200, { results: [], next: null, count: 0 })
            }
            if (pathname.endsWith('/signals/')) {
                return response(200, { signals: [] })
            }
            return response(200, reportFixture())
        }) as unknown as typeof fetch
        const items = (ids: string[]) => inboxFromReports(ids.map((id) => reportFixture({ id })))
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const signalsOf = (id: string) => paths.filter((path) => path.endsWith(`/reports/${id}/signals/`))
        const { result, rerender, unmount } = renderHook(
            ({ ids }: { ids: string[] }) => usePrefetchReports(items(ids), true),
            {
                initialProps: { ids: ['a', 'b'] },
                wrapper,
            }
        )
        expect(paths).toEqual([])
        act(() =>
            result.current.onViewableItemsChanged({
                viewableItems: [{ index: 0 }] as ViewToken<InboxItem>[],
                changed: [],
            })
        )
        await waitFor(() => expect(signalsOf('b')).toHaveLength(1))

        rerender({ ids: ['a', 'b', 'c'] })
        act(() =>
            result.current.onViewableItemsChanged({
                viewableItems: [{ index: 1 }] as ViewToken<InboxItem>[],
                changed: [],
            })
        )
        await waitFor(() => expect(signalsOf('c')).toHaveLength(1))

        expect(paths.filter((path) => path.includes('/today/'))).toEqual([
            '/api/projects/2/today/reports/a/page/',
            '/api/projects/2/today/reports/b/page/',
            '/api/projects/2/today/reports/c/page/',
        ])
        unmount()
        queryClient.clear()
    })
})
