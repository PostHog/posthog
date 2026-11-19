import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { setAuthProvider } from '@/api/client'
import type { IssueSort } from '@/api/errorTracking'
import type { ProjectScope } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { setAnalyticsClient } from '@/lib/analytics'

import { ErrorsListScreen } from './ErrorsListScreen'
import { useIssuesList } from './hooks'
import { filterRows, type IssueFilter } from './issueModel'

let mockScope: ProjectScope = { host: 'https://app.example.com', projectId: 2 }
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
jest.mock('@/features/views/useViewsAccess', () => ({
    reportScopeError: jest.fn(),
    useFeatureAccess: () => ({ state: 'ok' }),
}))
jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'))
jest.mock('react-native-worklets', () => require('react-native-worklets/src/mock'))
jest.mock('expo-router', () => ({
    Stack: {
        Toolbar: { Menu: () => null, Icon: () => null, Label: () => null, MenuAction: () => null, Button: () => null },
    },
    useRouter: () => ({ canGoBack: () => true, back: jest.fn(), push: jest.fn() }),
    useFocusEffect: jest.fn(),
    useIsFocused: () => true,
}))

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
    setAnalyticsClient(null)
    jest.restoreAllMocks()
})

test('requests small pages with hourly buckets, follows nextOffset, keeps data on failure and refreshes one page', async () => {
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
    const { result, unmount } = renderHook(() => useIssuesList('24h', 'all', 'users'), { wrapper })
    try {
        await waitFor(() => expect(result.current.hasMore).toBe(true))
        expect(bodies).toHaveLength(1)
        expect(bodies[0]).toMatchObject({
            limit: 15,
            offset: 0,
            volumeResolution: 24,
            orderBy: 'users',
            orderDirection: 'DESC',
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
        ({ filter }: { filter: IssueFilter }) => useIssuesList('24h', filter, 'users'),
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

test('resets pagination when changing range, sort, assignment or project', async () => {
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
        ({ window, filter, sort }: { window: '24h' | '7d'; filter: IssueFilter; sort: IssueSort }) =>
            useIssuesList(window, filter, sort),
        { wrapper, initialProps: { window: '24h', filter: 'all', sort: 'users' } }
    )
    try {
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-1'))
        rerender({ window: '7d', filter: 'all', sort: 'users' })
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-2'))
        expect(requests[1]?.body).toMatchObject({ offset: 0, dateRange: { date_from: '-7d' }, volumeResolution: 28 })
        rerender({ window: '7d', filter: 'all', sort: 'sessions' })
        expect(result.current.data).toBeUndefined()
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-3'))
        expect(requests[2]?.body).toMatchObject({ offset: 0, orderBy: 'sessions' })
        rerender({ window: '7d', filter: 'mine', sort: 'sessions' })
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-4'))
        expect(requests[3]?.body).toMatchObject({ offset: 0, assignee: { type: 'user', id: 7 } })
        mockScope = { ...mockScope, projectId: 3 }
        rerender({ window: '7d', filter: 'mine', sort: 'sessions' })
        expect(result.current.data).toBeUndefined()
        await waitFor(() => expect(result.current.data?.[0]?.id).toBe('issue-5'))
        expect(requests[4]?.url.pathname).toContain('/projects/3/')
        expect(requests[4]?.body.offset).toBe(0)
    } finally {
        unmount()
        client.clear()
    }
})

test('a sort picked in the sheet reloads the first page in that order and reports the change', async () => {
    const bodies: Record<string, unknown>[] = []
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
        if (!url.includes('query/issues/')) {
            return response({ results: [] })
        }
        bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        return response({
            results: [
                {
                    id: `issue-${bodies.length}`,
                    name: 'OperationalError',
                    aggregations: { users: 3, sessions: 0, occurrences: 1234, volumeRange: [0, 2, 5] },
                },
            ],
            hasMore: false,
        })
    }) as typeof fetch
    const capture = jest.fn()
    setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
    const { client, wrapper } = setup()
    render(
        <SafeAreaProvider
            initialMetrics={{
                frame: { x: 0, y: 0, width: 390, height: 844 },
                insets: { top: 44, bottom: 34, left: 0, right: 0 },
            }}
        >
            <ErrorsListScreen chrome="stack" />
        </SafeAreaProvider>,
        { wrapper }
    )
    try {
        const first = await screen.findByTestId('issue-row-issue-1')
        expect(within(first).getByText('1.23K')).toBeOnTheScreen()
        expect(within(first).getByText('–')).toBeOnTheScreen()
        fireEvent.press(screen.getByTestId('errors-sort-trigger'))
        fireEvent.press(screen.getByTestId('errors-sort-sessions'))
        await screen.findByTestId('issue-row-issue-2')
        expect(bodies[1]).toMatchObject({ offset: 0, orderBy: 'sessions', orderDirection: 'DESC' })
        expect(capture).toHaveBeenCalledWith('mobile_errors_sort_changed', {
            sort: 'sessions',
            previous: 'users',
            window: '24h',
        })
        expect(screen.getByText('Most sessions first')).toBeOnTheScreen()
    } finally {
        screen.unmount()
        client.clear()
    }
})
