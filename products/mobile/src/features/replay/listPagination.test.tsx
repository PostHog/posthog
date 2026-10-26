import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import type { ProjectScope } from '@/api/reports'

import { useSessionList } from './hooks'

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
jest.mock('expo-router', () => ({ useFocusEffect: jest.fn() }))

function response(body: unknown, status = 200): Response {
    return { ok: status < 400, status, headers: new Headers(), text: async () => JSON.stringify(body) } as Response
}

function setup(): { client: QueryClient; wrapper: ({ children }: { children: ReactNode }) => ReactElement } {
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retryDelay: 0 } } })
    return {
        client,
        wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    }
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
    jest.restoreAllMocks()
})

test('shows recordings while the deferred feed is pending and preserves their order when it arrives', async () => {
    let resolveRecordings: (value: Response) => void = () => undefined
    let resolveFeed: (value: Response) => void = () => undefined
    const requests: URL[] = []
    globalThis.fetch = jest.fn((url: string) => {
        requests.push(new URL(url))
        return new Promise<Response>((resolve) => {
            if (url.includes('session_recordings/')) {
                resolveRecordings = resolve
            } else {
                resolveFeed = resolve
            }
        })
    }) as typeof fetch
    const { client, wrapper } = setup()
    const { result, unmount } = renderHook(useSessionList, { wrapper })
    try {
        expect(requests).toHaveLength(1)
        expect(requests[0]?.searchParams.get('limit')).toBe('10')
        await act(async () => resolveRecordings(response({ results: [{ id: 'newest' }, { id: 'older' }] })))
        await waitFor(() => expect(result.current.rows.data?.map((row) => row.sessionId)).toEqual(['newest', 'older']))
        expect(requests).toHaveLength(2)
        expect(requests[1]?.searchParams.get('limit')).toBe('5')
        expect(result.current.rows.isLoading).toBe(false)
        await act(async () =>
            resolveFeed(
                response({
                    results: [
                        {
                            observation: {
                                id: 'obs-1',
                                session_id: 'older',
                                scanner_result: { model_output: { title: 'Interesting session' } },
                            },
                            reason: {},
                        },
                        { observation: { id: 'obs-2', session_id: 'recommended' }, reason: {} },
                    ],
                })
            )
        )
        await waitFor(() => expect(result.current.recommendations.map((row) => row.sessionId)).toEqual(['recommended']))
        expect(result.current.rows.data?.map((row) => row.sessionId)).toEqual(['newest', 'older'])
        expect(result.current.rows.data?.[1]?.title).toBe('Interesting session')
    } finally {
        unmount()
        client.clear()
    }
})

test('pages by cursor, keeps rows on failure, deduplicates, stops at the end and refreshes only the first page', async () => {
    const requests: URL[] = []
    let failNext = true
    globalThis.fetch = jest.fn(async (url: string) => {
        const request = new URL(url)
        if (!url.includes('session_recordings/')) {
            return response({ results: [] })
        }
        requests.push(request)
        if (request.searchParams.get('after')) {
            if (failNext) {
                failNext = false
                return response({ detail: 'Unavailable' }, 404)
            }
            return response({ results: [{ id: 'first' }, { id: 'second' }], has_next: false })
        }
        return response({ results: [{ id: 'first' }], has_next: true, next_cursor: 'next+cursor==' })
    }) as typeof fetch
    const { client, wrapper } = setup()
    const { result, unmount } = renderHook(useSessionList, { wrapper })
    try {
        await waitFor(() => expect(result.current.hasMore).toBe(true))
        expect(requests).toHaveLength(1)
        act(() => {
            result.current.loadMore()
            result.current.loadMore()
        })
        await waitFor(() => expect(result.current.loadMoreFailed).toBe(true))
        expect(requests).toHaveLength(2)
        expect(requests[1]?.searchParams.get('after')).toBe('next+cursor==')
        expect(result.current.rows.data?.map((row) => row.sessionId)).toEqual(['first'])
        expect(result.current.rows.isError).toBe(false)
        act(() => result.current.loadMore())
        await waitFor(() => expect(result.current.rows.data?.map((row) => row.sessionId)).toEqual(['first', 'second']))
        expect(result.current.hasMore).toBe(false)
        act(() => result.current.loadMore())
        expect(requests).toHaveLength(3)
        await act(async () => {
            await result.current.refresh()
        })
        await waitFor(() => expect(result.current.rows.data?.map((row) => row.sessionId)).toEqual(['first']))
        expect(requests).toHaveLength(4)
        expect(requests[3]?.searchParams.has('after')).toBe(false)
    } finally {
        unmount()
        client.clear()
    }
})
