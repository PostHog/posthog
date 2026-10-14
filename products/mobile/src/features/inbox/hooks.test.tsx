import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import { INBOX_PAGE_SIZE } from '@/api/reports'
import { reportFixture } from '@/model/adapters/testFixtures'

import { useInboxItems, useMarkReadOnOpen } from './hooks'

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
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2 }),
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
    })

    test('marks each report read on a fast Prev/Next', async () => {
        const queryClient = new QueryClient()
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
})
