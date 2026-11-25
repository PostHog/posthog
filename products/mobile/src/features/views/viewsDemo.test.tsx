import AsyncStorage from '@react-native-async-storage/async-storage'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { webOverviewQuery } from '@/api/webAnalytics'
import { useInternalUsersPreference } from '@/features/settings/internalUsersPreference'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import { insightQueryKey, webQueryKey } from './items'
import { useViewsList } from './pinHooks'
import { rangeOverride } from './rangeOverride'
import { customRange } from './rangePresets'
import { insightRangeKey, useViewCompareStore, useViewRangeStore, viewRangesLoaded } from './rangeStore'
import { viewsQueue } from './refreshQueue'
import { useDashboardScreen, useInsightScreen } from './viewHooks'
import { useWebAnalyticsScreen, useWebBreakdownList } from './webAnalytics/hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-router', () => {
    const { useEffect } = jest.requireActual<typeof import('react')>('react')
    return {
        useFocusEffect: (effect: () => undefined | (() => void)) => useEffect(effect, [effect]),
        useIsFocused: () => true,
    }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'demo',
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

let client = new QueryClient()

function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

async function advance(ms: number): Promise<void> {
    await act(async () => {
        jest.advanceTimersByTime(ms)
    })
}

describe('views in demo mode', () => {
    beforeEach(async () => {
        await viewRangesLoaded
        jest.useFakeTimers()
        viewsQueue.reset()
        useViewRangeStore.setState({ ranges: {} })
        useViewCompareStore.getState().clear()
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
    })

    afterEach(() => {
        viewsQueue.reset()
        client.clear()
        jest.useRealTimers()
    })

    test('refreshes immediately after open, then reads the cache inside the server window', async () => {
        const { result } = renderHook(() => useViewsList(), { wrapper })

        expect(result.current.pins.data?.map((pin) => [pin.kind, pin.ref, pin.display.mode])).toEqual([
            ['dashboard', 'demo-dash-kpis', 'number'],
            ['insight', 'demo-ins-signups', 'chart'],
        ])
        expect(result.current.refresh.status.text).toBe('Updating…')

        await advance(1000)
        expect(result.current.refresh.status.text).toBe('Updated 42 min ago')
        expect(result.current.refresh.blocked.blocked).toBe(false)
        act(() => result.current.refresh.onPull())
        await advance(1000)
        expect(result.current.refresh.status.text).toBe('Updated just now')
        expect(result.current.refresh.blocked.blocked).toBe(true)

        act(() => result.current.refresh.onPull())
        expect(result.current.refresh.pulling).toBe(true)
        await advance(1000)
        expect(result.current.refresh.status.text).toBe('Updated just now')
        expect(result.current.refresh.pulling).toBe(false)
        expect(result.current.refresh.busy).toBe(false)
        expect(result.current.refresh.hint).toBeNull()
    })

    test.each([
        { range: 'saved range', choice: null, dateFrom: '-7d' },
        { range: 'remembered range', choice: { kind: 'preset', key: '30d' } as const, dateFrom: '-30d' },
    ])('turns off a saved insight comparison on the $range', async ({ choice, dateFrom }) => {
        const shortId = 'demo-ins-dau'
        const snapshot = insightSnapshot(
            {
                id: 1,
                short_id: shortId,
                name: 'Daily active users',
                derived_name: null,
                query: {
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        series: [{ kind: 'EventsNode', event: '$pageview' }],
                        dateRange: { date_from: dateFrom },
                        compareFilter: { compare: true },
                    },
                },
                result: [
                    { action: { order: 0 }, days: ['2026-10-19'], data: [10], compare_label: 'current' },
                    { action: { order: 0 }, days: ['2026-10-12'], data: [5], compare_label: 'previous' },
                ],
                last_refresh: new Date().toISOString(),
                cache_target_age: null,
                next_allowed_client_refresh: null,
            },
            undefined,
            { readAt: Date.now(), serverNow: Date.now() }
        )
        useViewRangeStore.getState().setRange(insightRangeKey('demo', shortId), choice)
        client.setQueryData(
            insightQueryKey(null, { shortId, dashboardRef: null, override: rangeOverride(choice) }),
            snapshot
        )
        const { result, unmount } = renderHook(() => useInsightScreen(shortId, { from: 'browse' }), { wrapper })
        expect(result.current.range.compare).toBe(true)
        expect(result.current.comparing).toBe(true)

        act(() => result.current.range.setCompare(false))
        await advance(1000)

        expect(result.current.range.compare).toBe(false)
        expect(result.current.comparing).toBe(false)
        expect(result.current.insight.data?.query).toMatchObject({
            source: { dateRange: { date_from: dateFrom }, compareFilter: { compare: false } },
        })
        expect(result.current.insight.data?.allSeries.length).toBeGreaterThan(0)
        expect(result.current.insight.data?.allSeries.some((series) => series.compare === 'previous')).toBe(false)
        expect(result.current.insight.data?.delta?.basis).not.toBe('compare')
        unmount()
    })

    test('reopens each view on its remembered range and remembers a reset', async () => {
        const storageKey = useViewRangeStore.persist.getOptions().name
        if (!storageKey) {
            throw new Error('View range storage is unavailable')
        }
        const openDashboard = () =>
            renderHook(() => useDashboardScreen('demo-dash-kpis', { from: 'pinned' }), { wrapper })
        const openWebAnalytics = () => renderHook(() => useWebAnalyticsScreen({ from: 'pinned' }), { wrapper })
        const preset = { kind: 'preset', key: '30d' } as const
        const custom = customRange('2025-01-01', '2025-01-03')

        const restart = async (): Promise<void> => {
            const saved = await AsyncStorage.getItem(storageKey)
            useViewRangeStore.setState({ ranges: {} })
            if (saved !== null) {
                await AsyncStorage.setItem(storageKey, saved)
            }
            viewsQueue.reset()
            client.clear()
            await useViewRangeStore.persist.rehydrate()
        }

        const dashboard = openDashboard()
        const webAnalytics = openWebAnalytics()
        act(() => {
            dashboard.result.current.range.setChoice(preset, 'chip')
            webAnalytics.result.current.range.setChoice(custom, 'custom')
        })
        dashboard.unmount()
        webAnalytics.unmount()

        await restart()

        const reopenedDashboard = openDashboard()
        const reopenedWebAnalytics = openWebAnalytics()
        expect(reopenedDashboard.result.current.range.choice).toEqual(preset)
        expect(reopenedWebAnalytics.result.current.range.choice).toEqual(custom)
        act(() => reopenedDashboard.result.current.range.reset())
        reopenedDashboard.unmount()
        reopenedWebAnalytics.unmount()

        await restart()

        expect(openDashboard().result.current.range.choice).toBeNull()
        expect(openWebAnalytics().result.current.range.choice).toEqual(custom)
    })

    test('switches every Web analytics card and the full breakdown list to the filtered queries', async () => {
        const { result, unmount } = renderHook(
            () => ({
                screen: useWebAnalyticsScreen({ from: 'browse' }),
                list: useWebBreakdownList('pages', null),
            }),
            { wrapper }
        )
        try {
            await waitFor(() => expect(result.current.screen.overview.data).toBeDefined())

            act(() => useInternalUsersPreference.getState().setExclude(true))
            expect(result.current.screen.overview.data).toBeUndefined()
            const { screen, list } = result.current
            for (const item of [
                screen.trend,
                screen.retention,
                screen.activeHours,
                list.data,
                ...screen.tiles.map((tile) => tile.data),
            ]) {
                expect(JSON.parse(String(item.queryKey.at(-1)))).toMatchObject({ filterTestAccounts: true })
            }

            await waitFor(() => expect(result.current.screen.overview.data).toBeDefined())
            const filteredOverviewKey = webQueryKey(
                null,
                webOverviewQuery({ dateFrom: '-7d', dateTo: null, compare: true, filterTestAccounts: true })
            )
            expect(client.getQueryData(filteredOverviewKey)).toBe(result.current.screen.overview.data)
        } finally {
            unmount()
            act(() => useInternalUsersPreference.getState().setExclude(false))
        }
    })
})
