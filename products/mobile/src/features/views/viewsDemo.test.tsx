import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import { insightQueryKey } from './items'
import { useViewsList } from './pinHooks'
import { useViewRangeStore } from './rangeStore'
import { viewsQueue } from './refreshQueue'
import { useInsightScreen } from './viewHooks'

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
    beforeEach(() => {
        jest.useFakeTimers()
        viewsQueue.reset()
        useViewRangeStore.getState().clear()
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
            ['web_analytics', null, 'row'],
            ['notebook', 'demo-nb-launch', 'row'],
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

    test('turns off a saved insight comparison and loads the single-period result', async () => {
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
                        dateRange: { date_from: '-7d' },
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
        client.setQueryData(insightQueryKey(null, { shortId, dashboardRef: null, override: null }), snapshot)
        const { result, unmount } = renderHook(() => useInsightScreen(shortId, { from: 'browse' }), { wrapper })
        expect(result.current.range.compare).toBe(true)

        act(() => result.current.range.setCompare(false))
        await advance(1000)

        expect(result.current.range.compare).toBe(false)
        expect(result.current.comparing).toBe(false)
        expect(result.current.insight.data?.query).toMatchObject({ source: { compareFilter: { compare: false } } })
        expect(result.current.insight.data?.allSeries.length).toBeGreaterThan(0)
        expect(result.current.insight.data?.allSeries.some((series) => series.compare === 'previous')).toBe(false)
        expect(result.current.insight.data?.delta?.basis).not.toBe('compare')
        unmount()
    })
})
