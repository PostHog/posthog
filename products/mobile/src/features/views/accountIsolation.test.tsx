import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { webOverviewQuery } from '@/api/webAnalytics'
import { useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import { webOverviewSnapshot } from '@/model/adapters/webOverview'
import { dashboardQueryKey, insightQueryKey, webOverviewQueryKey } from './items'
import { viewsQueue } from './refreshQueue'
import { useDashboardScreen, useInsightScreen, useWebAnalyticsScreen } from './viewHooks'

let mockScope = { host: 'https://example.com', projectId: 1 }
jest.mock('expo-router', () => ({ useFocusEffect: () => {}, useIsFocused: () => false }))
jest.mock('@/demo/demoMode', () => ({ ...jest.requireActual('@/demo/demoMode'), useDataMode: () => 'live' }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('./useViewsAccess', () => ({
    ...jest.requireActual('./useViewsAccess'),
    useViewsAccess: () => ({ state: 'ok', missingScope: null }),
}))
let client: QueryClient
function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
describe('retained chart identity', () => {
    beforeEach(() => {
        mockScope = { host: 'https://example.com', projectId: 1 }
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        viewsQueue.reset()
    })
    afterEach(() => {
        client.clear()
        viewsQueue.reset()
    })
    test.each(['account', 'project', 'host', 'resource'])(
        'drops the displayed chart on a %s change',
        async (change) => {
            const snapshot = insightSnapshot(
                {
                    id: 1,
                    short_id: 'example-insight',
                    name: 'Example chart',
                    derived_name: null,
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [{ kind: 'EventsNode', event: '$pageview' }],
                            dateRange: { date_from: '-7d' },
                        },
                    },
                    result: [{ action: { order: 0 }, days: ['2026-10-19'], data: [42] }],
                    last_refresh: new Date().toISOString(),
                    cache_target_age: null,
                    next_allowed_client_refresh: null,
                },
                undefined,
                { readAt: Date.now(), serverNow: Date.now() }
            )
            client.setQueryData(
                insightQueryKey(mockScope, { shortId: 'example-insight', dashboardRef: null, override: null }),
                snapshot
            )
            client.setQueryData(dashboardQueryKey(mockScope, 'example-dashboard', null), {
                view: {
                    id: 1,
                    name: 'Example dashboard',
                    description: null,
                    savedRange: { dateFrom: null, dateTo: null },
                    lastRefresh: null,
                    tiles: [],
                },
                readAt: Date.now(),
                refreshFailed: false,
            })
            const webQuery = webOverviewQuery({ dateFrom: '-7d', dateTo: null, compare: true })
            client.setQueryData(
                webOverviewQueryKey(mockScope, webQuery),
                webOverviewSnapshot({ results: [{ key: 'visitors', kind: 'unit', value: 42 }] }, undefined, Date.now())
            )
            const { result, rerender, unmount } = renderHook(
                ({ shortId }: { shortId: string }) => ({
                    insight: useInsightScreen(shortId, { from: 'browse' }),
                    dashboard: useDashboardScreen(
                        shortId === 'example-insight' ? 'example-dashboard' : 'other-dashboard',
                        { from: 'browse' }
                    ),
                    web: useWebAnalyticsScreen({ from: 'browse' }),
                }),
                { wrapper, initialProps: { shortId: 'example-insight' } }
            )
            expect(result.current.insight.insight.data?.name).toBe('Example chart')
            expect(result.current.dashboard.dashboard.data?.name).toBe('Example dashboard')
            expect(result.current.web.overview.data?.metrics[0]?.value).toBe(42)
            await act(async () => {
                client.clear()
                if (change === 'project') mockScope = { ...mockScope, projectId: 2 }
                if (change === 'host') mockScope = { ...mockScope, host: 'https://other.example.com' }
                if (change === 'account') {
                    setSessionTokens(null)
                    useAuthStore.setState({ user: null })
                }
                rerender({ shortId: change === 'resource' ? 'other-insight' : 'example-insight' })
            })
            expect(result.current.insight.insight.data).toBeUndefined()
            expect(result.current.dashboard.dashboard.data).toBeUndefined()
            if (change !== 'resource') expect(result.current.web.overview.data).toBeUndefined()
            unmount()
        }
    )
})
