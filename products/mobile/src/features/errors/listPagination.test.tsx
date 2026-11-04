import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import type { ProjectScope } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'

import { useIssuesList } from './hooks'
import { filterRows, type IssueFilter } from './issueModel'

let mockScope: ProjectScope = { host: 'https://app.example.com', projectId: 2 }
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
jest.mock('@/features/views/useViewsAccess', () => ({ reportScopeError: jest.fn() }))

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
    useAuthStore.setState({
        user: { id: 7, uuid: 'viewer', distinctId: 'viewer', email: 'person@example.com', name: 'Person' },
    })
    setAuthProvider({
        getAuth: () => ({ ...mockScope, accessToken: 'fake-token', session: 1 }),
        refreshAccessToken: async () => null,
    })
})
afterEach(() => {
    setAuthProvider(null)
    jest.restoreAllMocks()
})

test('requests small counts-only pages, follows nextOffset, keeps data on failure and refreshes one page', async () => {
    const bodies: Record<string, unknown>[] = []
    let failNext = true
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
        if (!url.includes('query/issues/')) {
            return response({ results: [] })
        }
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        bodies.push(body)
        if (body.offset === 40) {
            if (failNext) {
                failNext = false
                return response({ detail: 'Unavailable' }, 404)
            }
            return response({ results: [{ id: 'first' }, { id: 'second' }], hasMore: false })
        }
        return response({ results: [{ id: 'first' }], hasMore: true, nextOffset: 40 })
    }) as typeof fetch
    const { client, wrapper } = setup()
    const { result, unmount } = renderHook(() => useIssuesList('24h', 'all'), { wrapper })
    try {
        await waitFor(() => expect(result.current.hasMore).toBe(true))
        expect(bodies).toHaveLength(1)
        expect(bodies[0]).toMatchObject({
            limit: 15,
            offset: 0,
            volumeResolution: 0,
            orderBy: 'users',
            dateRange: { date_from: '-24h' },
        })
        act(() => {
            result.current.loadMore()
            result.current.loadMore()
        })
        await waitFor(() => expect(result.current.loadMoreFailed).toBe(true))
        expect(bodies).toHaveLength(2)
        expect(bodies[1]?.offset).toBe(40)
        expect(result.current.data?.map((row) => row.id)).toEqual(['first'])
        expect(result.current.isError).toBe(false)
        act(() => result.current.loadMore())
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['first', 'second']))
        expect(result.current.hasMore).toBe(false)
        act(() => result.current.loadMore())
        expect(bodies).toHaveLength(3)
        await act(async () => {
            await result.current.onPull()
        })
        await waitFor(() => expect(result.current.data?.map((row) => row.id)).toEqual(['first']))
        expect(bodies).toHaveLength(4)
        expect(bodies[3]?.offset).toBe(0)
    } finally {
        unmount()
        client.clear()
    }
})

test('New and Spiking can find matches on later pages without eager paging or treating pending spikes as final', async () => {
    const requests: URL[] = []
    let resolveSpikes: (value: Response) => void = () => undefined
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
        const request = new URL(url)
        requests.push(request)
        if (url.includes('spike_events/')) {
            if (request.searchParams.get('issue_ids') === 'new') {
                return new Promise<Response>((resolve) => {
                    resolveSpikes = resolve
                })
            }
            return response({ results: [] })
        }
        const body = JSON.parse(String(init?.body)) as { offset: number }
        return body.offset === 0
            ? response({ results: [{ id: 'old', first_seen: '2020-01-01T00:00:00Z' }], hasMore: true, nextOffset: 15 })
            : response({ results: [{ id: 'new', first_seen: new Date().toISOString() }], hasMore: false })
    }) as typeof fetch
    const { client, wrapper } = setup()
    const { result, rerender, unmount } = renderHook(
        ({ filter }: { filter: IssueFilter }) => useIssuesList('24h', filter),
        {
            wrapper,
            initialProps: { filter: 'new' },
        }
    )
    try {
        await waitFor(() => expect(result.current.data).toHaveLength(1))
        expect(filterRows(result.current.data ?? [], 'new')).toEqual([])
        expect(result.current.hasMore).toBe(true)
        expect(requests.filter((request) => request.pathname.includes('query/issues/'))).toHaveLength(1)
        act(() => result.current.loadMore())
        await waitFor(() => expect(filterRows(result.current.data ?? [], 'new').map((row) => row.id)).toEqual(['new']))
        rerender({ filter: 'spiking' })
        expect(result.current.spikesLoading).toBe(true)
        expect(filterRows(result.current.data ?? [], 'spiking')).toEqual([])
        await act(async () =>
            resolveSpikes(response({ results: [{ issue: { id: 'new' }, detected_at: new Date().toISOString() }] }))
        )
        await waitFor(() =>
            expect(filterRows(result.current.data ?? [], 'spiking').map((row) => row.id)).toEqual(['new'])
        )
        expect(requests.filter((request) => request.pathname.includes('spike_events/'))).toHaveLength(2)
    } finally {
        unmount()
        client.clear()
    }
})

test('resets pagination when changing range, assignment or project', async () => {
    const requests: { url: URL; body: Record<string, unknown> }[] = []
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
        if (!url.includes('query/issues/')) {
            return response({ results: [] })
        }
        requests.push({ url: new URL(url), body: JSON.parse(String(init?.body)) as Record<string, unknown> })
        return response({ results: [{ id: `issue-${requests.length}` }], hasMore: false })
    }) as typeof fetch
    const { client, wrapper } = setup()
    const { result, rerender, unmount } = renderHook(
        ({ window, filter }: { window: '24h' | '7d'; filter: IssueFilter }) => useIssuesList(window, filter),
        { wrapper, initialProps: { window: '24h', filter: 'all' } }
    )
    try {
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-1'))
        rerender({ window: '7d', filter: 'all' })
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-2'))
        expect(requests[1]?.body).toMatchObject({ offset: 0, dateRange: { date_from: '-7d' } })
        rerender({ window: '7d', filter: 'mine' })
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-3'))
        expect(requests[2]?.body).toMatchObject({ offset: 0, assignee: { type: 'user', id: 7 } })
        mockScope = { ...mockScope, projectId: 3 }
        rerender({ window: '7d', filter: 'mine' })
        expect(result.current.data).toBeUndefined()
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-4'))
        expect(requests[3]?.url.pathname).toContain('/projects/3/')
        expect(requests[3]?.body.offset).toBe(0)
    } finally {
        unmount()
        client.clear()
    }
})
