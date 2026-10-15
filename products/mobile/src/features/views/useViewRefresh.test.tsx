import { focusManager } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'

import type { Freshness } from '@/model/views'

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

    // Written relative to now: an old read whose window has passed, so a drawable insight is due and may force.
    function oldValue(): Freshness {
        const longAgo = new Date(Date.now() - 3_600_000).toISOString()
        return {
            lastRefreshAt: longAgo,
            cacheTargetAge: longAgo,
            nextAllowedRefreshAt: longAgo,
            readAt: Date.now() - 3_600_000,
            refreshFailed: false,
        }
    }

    test.each<[string, (() => Freshness) | null, boolean, string[]]>([
        [
            'an insight the phone cannot draw gets only cache reads from the button and pull',
            oldValue,
            false,
            ['force_cache', 'force_cache'],
        ],
        [
            'an old insight the phone draws',
            oldValue,
            true,
            ['blocking', 'blocking', 'force_blocking', 'force_blocking'],
        ],
        [
            'a cold open, whose kind is unknown, still reads with blocking',
            null,
            true,
            ['blocking', 'blocking', 'blocking', 'blocking'],
        ],
    ])('on the insight screen, %s', async (_name, value, canDraw, modes) => {
        jest.useFakeTimers()
        try {
            const sent: string[] = []
            const item: RefreshItem = {
                key: 'insight-abc',
                family: 'insights',
                windowMode: 'force_cache',
                snapshot: value ? () => value() : () => undefined,
                drawable: () => canDraw,
                read: (mode) => {
                    sent.push(mode)
                    return Promise.resolve(OK)
                },
            }
            const props: ViewRefreshOptions = {
                screen: 'insight',
                dataScope: 'https://us.example.com|1',
                screenKey: 'insight:abc',
                items: [item],
                bulkFloor: false,
                enabled: true,
            }
            const { result, unmount } = renderHook(() => useViewRefresh(props))
            await flush()
            // Past the queue's one-read-per-minute floor before each next pass.
            const nextMinute = async (): Promise<void> => {
                await act(async () => {
                    jest.advanceTimersByTime(61_000)
                })
            }
            await nextMinute()
            act(() => focusManager.setFocused(false))
            await nextMinute()
            act(() => focusManager.setFocused(true))
            await flush()
            await nextMinute()
            act(() => result.current.onButton())
            await flush()
            await nextMinute()
            act(() => result.current.onPull())
            await flush()

            expect(sent).toEqual(modes)
            unmount()
        } finally {
            focusManager.setFocused(undefined)
            jest.useRealTimers()
        }
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
