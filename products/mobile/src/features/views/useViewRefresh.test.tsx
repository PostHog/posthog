import { act, renderHook } from '@testing-library/react-native'

import type { ReadResult } from './refreshQueue'
import { viewsQueue } from './refreshQueue'
import { type RefreshContainer, type RefreshItem, useViewRefresh, type ViewRefreshOptions } from './useViewRefresh'

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

const OK: ReadResult = { status: 'ok', computed: true }

describe('useViewRefresh on a dashboard', () => {
    let reads: string[]
    let waiting: Map<string, () => void>

    function read(key: string, deferred: boolean): () => Promise<ReadResult> {
        return () => {
            reads.push(key)
            if (!deferred) {
                return Promise.resolve(OK)
            }
            return new Promise<ReadResult>((resolve) => waiting.set(key, () => resolve(OK)))
        }
    }

    function tiles(range: string, count: number, deferred: boolean): RefreshItem[] {
        return Array.from({ length: count }, (_, index) => {
            const key = `${range}-tile-${index}`
            return {
                key,
                family: 'insights',
                windowMode: 'force_cache',
                snapshot: () => undefined,
                read: read(key, deferred),
            }
        })
    }

    function dashboard(range: string): RefreshContainer {
        const key = `${range}-dashboard`
        return { key, family: 'dashboards', readAt: () => null, lastRefresh: () => null, read: read(key, false) }
    }

    function options(range: string, items: RefreshItem[]): ViewRefreshOptions {
        return {
            screen: 'dashboard',
            dataScope: 'https://us.example.com|1',
            screenKey: 'dashboard:1',
            items,
            container: dashboard(range),
            bulkFloor: true,
            enabled: true,
            rangeKey: range,
        }
    }

    async function flush(): Promise<void> {
        await act(async () => {
            for (let tick = 0; tick < 10; tick += 1) {
                await Promise.resolve()
            }
        })
    }

    async function settle(key: string): Promise<void> {
        waiting.get(key)?.()
        waiting.delete(key)
        await flush()
    }

    beforeEach(() => {
        reads = []
        waiting = new Map()
        viewsQueue.reset()
    })

    test('computes only the first rows before the list reports what it shows', async () => {
        const { unmount } = renderHook(() => useViewRefresh(options('7d', tiles('7d', 10, false))))
        await flush()

        expect(reads).toEqual([
            '7d-dashboard',
            '7d-tile-0',
            '7d-tile-1',
            '7d-tile-2',
            '7d-tile-3',
            '7d-tile-4',
            '7d-tile-5',
        ])
        unmount()
    })

    test('never computes a tile the phone cannot draw', async () => {
        const [drawn, web] = tiles('7d', 2, false)
        const items = [
            { ...drawn, drawable: () => true },
            { ...web, drawable: () => false },
        ] as RefreshItem[]
        const { unmount } = renderHook(() => useViewRefresh(options('7d', items)))
        await flush()

        expect(reads).toEqual(['7d-dashboard', '7d-tile-0'])
        unmount()
    })

    test('Load on a tile read within the last minute still sends one blocking read', async () => {
        const { result, unmount } = renderHook(() => useViewRefresh(options('7d', tiles('7d', 1, false))))
        await flush()

        act(() => {
            result.current.refreshItem('7d-tile-0')
        })
        await flush()

        expect(reads).toEqual(['7d-dashboard', '7d-tile-0', '7d-tile-0'])
        unmount()
    })

    test('"Try again" reads a dashboard that failed to load, inside its minute floor', async () => {
        const failedOnce: RefreshContainer = {
            ...dashboard('7d'),
            read: () => {
                reads.push('7d-dashboard')
                return reads.length === 1 ? Promise.reject(new Error('Network request failed')) : Promise.resolve(OK)
            },
        }
        const props = { ...options('7d', []), container: failedOnce }
        const { result, unmount } = renderHook(() => useViewRefresh(props))
        await flush()

        act(() => result.current.retry())
        await flush()

        expect(reads).toEqual(['7d-dashboard', '7d-dashboard'])
        unmount()
    })

    test('a new range drops the queued reads of the range left, and its own reads go next', async () => {
        const { rerender, unmount } = renderHook((props: ViewRefreshOptions) => useViewRefresh(props), {
            initialProps: options('7d', tiles('7d', 6, true)),
        })
        await flush()
        expect(reads).toEqual(['7d-dashboard', '7d-tile-0', '7d-tile-1'])

        rerender(options('30d', tiles('30d', 6, true)))
        await flush()
        // The two running computes finish, because the server runs them anyway.
        await settle('7d-tile-0')
        await settle('7d-tile-1')

        expect(reads).toEqual(['7d-dashboard', '7d-tile-0', '7d-tile-1', '30d-dashboard', '30d-tile-0', '30d-tile-1'])
        unmount()
    })
})
