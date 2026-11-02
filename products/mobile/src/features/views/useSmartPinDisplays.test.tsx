import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { type DashboardApi, fetchDashboard, fetchRecentDashboards } from '@/api/dashboards'
import { fetchInsightMetadata, fetchInsightPage, type InsightApi, readInsight } from '@/api/insights'
import type { PaginatedApi, ProjectScope } from '@/api/reports'
import { createShortcut, deleteShortcut, type FileSystemShortcutApi, fetchShortcuts } from '@/api/shortcuts'
import { useAuthStore } from '@/auth/authStore'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import type { InsightSnapshot, PinView } from '@/model/views'

import { dashboardContainer, insightItem, insightQueryKey } from './items'
import { usePinActions, useViewsList } from './pinHooks'
import { usePinPrefs } from './pinPrefsStore'
import { viewsQueue } from './refreshQueue'
import { discoverPinDisplays } from './useSmartPinDisplays'
import { viewsKeys } from './viewsCache'

jest.mock('expo-router', () => {
    const { useEffect } = jest.requireActual<typeof import('react')>('react')
    return {
        useFocusEffect: (effect: () => undefined | (() => void)) => useEffect(effect, [effect]),
        useIsFocused: () => mockFocused,
    }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
let mockScope: ProjectScope = { host: 'https://example.com', projectId: 1 }
let mockFocused = true
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/api/dashboards', () => ({
    ...jest.requireActual<typeof import('@/api/dashboards')>('@/api/dashboards'),
    fetchDashboard: jest.fn(),
    fetchRecentDashboards: jest.fn(),
}))
jest.mock('@/api/insights', () => ({
    ...jest.requireActual<typeof import('@/api/insights')>('@/api/insights'),
    fetchInsightPage: jest.fn(),
    fetchInsightMetadata: jest.fn(),
    readInsight: jest.fn(),
}))
jest.mock('@/api/shortcuts', () => ({
    ...jest.requireActual<typeof import('@/api/shortcuts')>('@/api/shortcuts'),
    fetchShortcuts: jest.fn(),
    createShortcut: jest.fn(),
    deleteShortcut: jest.fn(),
}))

let client: QueryClient
let previousAuth: ReturnType<typeof useAuthStore.getState>

function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function page<T>(results: T[]): PaginatedApi<T> {
    return { count: results.length, next: null, results }
}

function insight(id: number, result: InsightApi['result'] = null, dateFrom = '-7d'): InsightApi {
    return {
        id,
        short_id: `ins-${id}`,
        name: `Metric ${id}`,
        derived_name: null,
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                trendsFilter: { display: 'ActionsLineGraph' },
                dateRange: { date_from: dateFrom, date_to: null },
            },
        },
        result,
        last_refresh: result === null ? null : new Date().toISOString(),
        cache_target_age: new Date(Date.now() + 3_600_000).toISOString(),
        next_allowed_client_refresh: null,
    }
}

function dashboard(id: number): DashboardApi {
    return { id, name: `Dashboard ${id}`, tiles: [{ id: id * 100, insight: insight(id * 10) }] }
}

function valueResult(): unknown {
    return [{ data: [42], days: ['2026-10-19'], aggregated_value: 42 }]
}

function shortcut(id: number, kind = 'dashboard'): FileSystemShortcutApi {
    return {
        id: `pin-${id}`,
        type: kind,
        ref: kind === 'insight' ? `ins-${id}` : String(id),
        path: `View ${id}`,
        href: null,
        order: id,
        created_at: '2026-10-20T12:00:00Z',
    }
}

const projectKey = `${mockScope.host}|${mockScope.projectId}`

describe('automatic displays for actual Views pins', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockScope = { host: 'https://example.com', projectId: 1 }
        mockFocused = true
        previousAuth = useAuthStore.getState()
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: mockScope.host,
            projectId: mockScope.projectId,
        })
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } })
        viewsQueue.reset()
        usePinPrefs.getState().clear()
        jest.mocked(fetchShortcuts).mockResolvedValue(page([]))
        jest.mocked(fetchRecentDashboards).mockResolvedValue(page([]))
        jest.mocked(fetchInsightPage).mockResolvedValue(page([]))
        jest.mocked(fetchInsightMetadata).mockImplementation(async (shortId) =>
            insight(Number(shortId.replace('ins-', '')))
        )
        jest.mocked(fetchDashboard).mockImplementation(async (id) => dashboard(id))
        jest.mocked(readInsight).mockImplementation(async (target) =>
            insight(target.id ?? Number(target.shortId.replace('ins-', '')), valueResult())
        )
    })

    afterEach(() => {
        viewsQueue.reset()
        client.clear()
        usePinPrefs.getState().clear()
        useAuthStore.setState(previousAuth)
    })

    test.each(['missing', 'stale'])(
        'keeps real pins in order, honors an explicit Row and computes %s dashboard results',
        async (cached) => {
            if (cached === 'stale') {
                jest.mocked(fetchDashboard).mockImplementation(async (id) => {
                    const response = dashboard(id)
                    const tile = response.tiles?.[0]?.insight
                    if (tile) {
                        tile.result = valueResult()
                        tile.last_refresh = new Date(Date.now() - 3_600_000).toISOString()
                        tile.cache_target_age = tile.last_refresh
                    }
                    return response
                })
            }
            usePinPrefs.getState().setDisplay(projectKey, 'pin-1', { mode: 'row' })
            const rows = Array.from({ length: 8 }, (_, index) => shortcut(index + 1))
            let finishPins: (value: Awaited<ReturnType<typeof fetchShortcuts>>) => void = () => undefined
            jest.mocked(fetchShortcuts).mockReturnValue(
                new Promise((resolve) => {
                    finishPins = resolve
                })
            )
            const { result, unmount } = renderHook(() => useViewsList(), { wrapper })
            await waitFor(() => expect(fetchShortcuts).toHaveBeenCalledTimes(1))
            expect(fetchDashboard).not.toHaveBeenCalled()
            await act(async () => finishPins(page(rows)))
            await waitFor(() => expect(result.current.pins.data?.[1]?.display.mode).toBe('chart'))
            await waitFor(() => expect(readInsight).toHaveBeenCalledTimes(3))
            expect(result.current.pins.data?.map((pin) => pin.shortcutId)).toEqual(rows.map((row) => row.id))
            expect(result.current.pins.data?.map((pin) => pin.display.mode)).toEqual([
                'row',
                'chart',
                'chart',
                'chart',
                'row',
                'row',
                'row',
                'row',
            ])
            expect(result.current.pins.data?.[1]?.display).toEqual({
                mode: 'chart',
                tileId: 200,
                insightId: 20,
                insightShortId: 'ins-20',
            })
            expect(jest.mocked(fetchDashboard).mock.calls.map(([id]) => id)).toEqual([2, 3, 4])
            const pin = result.current.pins.data?.[1] as PinView
            expect(
                client.getQueryData<InsightSnapshot>(
                    insightQueryKey(mockScope, {
                        id: pin.display.insightId,
                        shortId: pin.display.insightShortId as string,
                        dashboardRef: pin.ref,
                        override: null,
                    })
                )?.value
            ).toBe(42)
            expect(fetchInsightPage).not.toHaveBeenCalled()
            expect(createShortcut).not.toHaveBeenCalled()
            expect(deleteShortcut).not.toHaveBeenCalled()
            expect(usePinPrefs.getState().projects[projectKey]?.display).toEqual({ 'pin-1': { mode: 'row' } })
            unmount()
        }
    )

    test('keeps an empty pin list empty without discovering unpinned views', async () => {
        jest.mocked(fetchRecentDashboards).mockResolvedValue(page([{ id: 1, name: 'Recent dashboard' }]))
        const { result, unmount } = renderHook(() => useViewsList(), { wrapper })
        await waitFor(() => expect(result.current.pins.data).toEqual([]))
        expect(fetchDashboard).not.toHaveBeenCalled()
        expect(fetchInsightMetadata).not.toHaveBeenCalled()
        expect(fetchInsightPage).not.toHaveBeenCalled()
        expect(createShortcut).not.toHaveBeenCalled()
        unmount()
    })

    test('persists selecting the current automatic mode and keeps later explicit Row choices', async () => {
        jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1)]))
        const { result, unmount } = renderHook(() => ({ list: useViewsList(), actions: usePinActions() }), { wrapper })
        await waitFor(() => expect(result.current.list.pins.data?.[0]?.display.mode).toBe('chart'))
        const automatic = result.current.list.pins.data?.[0] as PinView
        expect(usePinPrefs.getState().projects[projectKey]?.display['pin-1']).toBeUndefined()
        act(() => {
            result.current.actions.setDisplayMode(automatic, 'chart')
        })
        expect(usePinPrefs.getState().projects[projectKey]?.display['pin-1']).toEqual(automatic.display)
        act(() => {
            result.current.actions.setDisplayMode(automatic, 'row')
        })
        await waitFor(() => expect(result.current.list.pins.data?.[0]?.display.mode).toBe('row'))
        expect(usePinPrefs.getState().projects[projectKey]?.display['pin-1']?.mode).toBe('row')
        expect(fetchDashboard).toHaveBeenCalledTimes(1)
        unmount()
    })

    test('unpinning an automatic visual removes the real shortcut and never recreates it', async () => {
        jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1)]))
        const { result, unmount } = renderHook(() => ({ list: useViewsList(), actions: usePinActions() }), { wrapper })
        await waitFor(() => expect(result.current.list.pins.data?.[0]?.display.mode).toBe('chart'))
        const pin = result.current.list.pins.data?.[0] as PinView
        await act(async () => {
            await result.current.actions.unpin(pin, 'row_menu')
        })
        await waitFor(() => expect(result.current.list.pins.data).toEqual([]))
        expect(deleteShortcut).toHaveBeenCalledWith('pin-1')
        expect(createShortcut).not.toHaveBeenCalled()
        unmount()
    })

    test.each([false, true])(
        'uses Row visibility after the automatic display resolves: initially visible %s',
        async (visible) => {
            let finishMetadata: (value: Awaited<ReturnType<typeof fetchInsightMetadata>>) => void = () => undefined
            jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1, 'insight')]))
            jest.mocked(fetchInsightMetadata).mockReturnValue(
                new Promise((resolve) => {
                    finishMetadata = resolve
                })
            )
            const { result, unmount } = renderHook(() => useViewsList(), { wrapper })
            await waitFor(() => expect(fetchInsightMetadata).toHaveBeenCalledTimes(1))
            const tokens = [{ item: { shortcutId: 'pin-1' }, key: 'pin:pin-1', index: 0, isViewable: true }]
            act(() => result.current.onViewableItemsChanged({ viewableItems: visible ? tokens : [] }))
            await act(async () => finishMetadata(insight(1)))
            await waitFor(() => expect(result.current.pins.data?.[0]?.display.mode).toBe('chart'))
            if (!visible) {
                expect(readInsight).not.toHaveBeenCalled()
                act(() => result.current.onViewableItemsChanged({ viewableItems: tokens }))
            }
            await waitFor(() => expect(readInsight).toHaveBeenCalledTimes(1))
            unmount()
        }
    )

    test('an explicit dashboard preview still rechecks after five minutes inside a longer cache target', async () => {
        const display = { mode: 'chart' as const, tileId: 100, insightId: 10, insightShortId: 'ins-10' }
        usePinPrefs.getState().setDisplay(projectKey, 'pin-1', display)
        jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1)]))
        const response = insight(10, valueResult())
        client.setQueryData(
            insightQueryKey(mockScope, { id: 10, shortId: 'ins-10', dashboardRef: '1', override: null }),
            insightSnapshot(response, undefined, { readAt: Date.now() - 6 * 60_000, serverNow: Date.now() })
        )
        const { unmount } = renderHook(() => useViewsList(), { wrapper })
        await waitFor(() => expect(readInsight).toHaveBeenCalledTimes(1))
        expect(readInsight).toHaveBeenCalledWith(
            { id: 10, shortId: 'ins-10' },
            expect.objectContaining({ refresh: 'blocking' })
        )
        expect(fetchDashboard).not.toHaveBeenCalled()
        unmount()
    })

    test.each(['focus', 'project'])('cancels optional metadata when the %s changes', async (change) => {
        jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1, 'insight')]))
        let oldSignal: AbortSignal | undefined
        jest.mocked(fetchInsightMetadata)
            .mockImplementationOnce(
                (_id, signal) =>
                    new Promise((_resolve, reject) => {
                        oldSignal = signal
                        signal?.addEventListener(
                            'abort',
                            () => {
                                const error = new Error('Aborted')
                                error.name = 'AbortError'
                                reject(error)
                            },
                            { once: true }
                        )
                    })
            )
            .mockResolvedValue(insight(1))
        const oldScope = mockScope
        const { result, rerender, unmount } = renderHook(() => useViewsList(), { wrapper })
        await waitFor(() => expect(fetchInsightMetadata).toHaveBeenCalledTimes(1))
        if (change === 'focus') {
            mockFocused = false
        } else {
            mockScope = { host: 'https://example.com', projectId: 2 }
        }
        rerender({})
        await waitFor(() => expect(oldSignal?.aborted).toBe(true))
        expect(client.getQueryData(viewsKeys.pinMetadata(oldScope, 'ins-1'))).toBeUndefined()
        if (change === 'project') {
            await waitFor(() => expect(result.current.pins.data?.[0]?.display.mode).toBe('chart'))
            expect(fetchInsightMetadata).toHaveBeenCalledTimes(2)
            expect(client.getQueryData(viewsKeys.pinMetadata(mockScope, 'ins-1'))).toBeDefined()
        }
        unmount()
    })

    test('failed optional metadata keeps the actual pin as a row and can retry', async () => {
        jest.mocked(fetchShortcuts).mockResolvedValue(page([shortcut(1, 'insight')]))
        jest.mocked(fetchInsightMetadata).mockRejectedValue(new ApiError(503, {}))
        const { result, unmount } = renderHook(() => useViewsList(), { wrapper })
        await waitFor(() => expect(fetchInsightMetadata).toHaveBeenCalledTimes(1))
        expect(result.current.pins.data).toMatchObject([{ shortcutId: 'pin-1', display: { mode: 'row' } }])
        expect(result.current.pins.isError).toBe(false)
        unmount()
    })

    test('canceling optional metadata during a family pause sends no request', async () => {
        viewsQueue.notePause('insights', new ApiError(429, {}, new Headers({ 'Retry-After': '60' })))
        const controller = new AbortController()
        const pin = { kind: 'insight', ref: 'ins-1', shortcutId: 'pin-1', native: true } as PinView
        const run = discoverPinDisplays(
            { client, scope: mockScope, demo: false },
            [pin],
            controller.signal,
            'cancel-test'
        )
        controller.abort()
        await expect(run).rejects.toMatchObject({ name: 'AbortError' })
        expect(fetchInsightMetadata).not.toHaveBeenCalled()
    })

    test('a delayed dashboard cache response preserves a newer insight value while newer dashboard data still updates', async () => {
        let finishDashboard: (response: DashboardApi) => void = () => undefined
        jest.mocked(fetchDashboard).mockReturnValue(
            new Promise((resolve) => {
                finishDashboard = resolve
            })
        )
        const context = { client, scope: mockScope, demo: false }
        const target = { id: 10, shortId: 'ins-10', dashboardRef: '1', override: null }
        const container = dashboardContainer(context, '1', null)
        const delayed = container.read(new AbortController().signal)
        await insightItem(context, target).read('force_blocking', new AbortController().signal)
        const queryKey = insightQueryKey(mockScope, target)
        const current = client.getQueryData<InsightSnapshot>(queryKey)
        const previous = dashboard(1)
        const older = previous.tiles?.[0]?.insight
        if (older) {
            older.result = [{ data: [7], days: ['2026-10-19'], aggregated_value: 7 }]
            older.last_refresh = new Date(Date.parse(current?.lastRefreshAt ?? '') - 60_000).toISOString()
        }
        finishDashboard(previous)
        await delayed
        expect(client.getQueryData<InsightSnapshot>(queryKey)?.value).toBe(42)
        expect(client.getQueryData<InsightSnapshot>(queryKey)?.lastRefreshAt).toBe(current?.lastRefreshAt)

        const updated = dashboard(1)
        const newer = updated.tiles?.[0]?.insight
        if (newer) {
            newer.result = [{ data: [91], days: ['2026-10-19'], aggregated_value: 91 }]
            newer.last_refresh = new Date(Date.parse(current?.lastRefreshAt ?? '') + 60_000).toISOString()
        }
        jest.mocked(fetchDashboard).mockResolvedValue(updated)
        await container.read(new AbortController().signal)
        expect(client.getQueryData<InsightSnapshot>(queryKey)?.value).toBe(91)

        if (older) {
            older.query = insight(10, older.result, '-30d').query
        }
        jest.mocked(fetchDashboard).mockResolvedValue(previous)
        await container.read(new AbortController().signal)
        expect(client.getQueryData<InsightSnapshot>(queryKey)?.value).toBe(7)
        expect(client.getQueryData<InsightSnapshot>(queryKey)?.savedRange.dateFrom).toBe('-30d')
    })
})
