import { focusManager } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'

import type { Freshness } from '@/model/views'

import { REFRESH_MIN_MS } from './freshness'
import type { ReadResult, RefreshMode } from './refreshQueue'
import { viewsQueue } from './refreshQueue'
import { type RefreshContainer, type RefreshItem, useViewRefresh, type ViewRefreshOptions } from './useViewRefresh'
import { useItemErrors } from './viewsCache'

let mockFocused = true

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-router', () => {
    const { useEffect } = jest.requireActual<typeof import('react')>('react')
    return {
        useFocusEffect: (effect: () => undefined | (() => void)) =>
            useEffect(() => {
                if (mockFocused) {
                    return effect()
                }
                return undefined
            }, [effect, mockFocused]),
        useIsFocused: () => mockFocused,
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
        mockFocused = true
        reads = []
        waiting = new Map()
        viewsQueue.reset()
        useItemErrors.getState().reset()
    })

    afterEach(async () => {
        for (const resolve of waiting.values()) {
            resolve()
        }
        await flush()
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

    test.each(['fresh list', 'refresh window', 'fast list', 'slow list', 'failed list'] as const)(
        'a pull gives feedback and settles with %s',
        async (scenario) => {
            jest.useFakeTimers()
            try {
                let finish: (() => void) | undefined
                const refetch = jest.fn(() => {
                    if (scenario === 'slow list' || scenario === 'failed list') {
                        return new Promise<void>((resolve, reject) => {
                            finish = () =>
                                scenario === 'failed list' ? reject(new Error('Network request failed')) : resolve()
                        })
                    }
                    return Promise.resolve()
                })
                const snapshot: Freshness = {
                    ...oldValue(),
                    readAt: Date.now(),
                    nextAllowedRefreshAt: new Date(Date.now() + 60_000).toISOString(),
                }
                const props: ViewRefreshOptions = {
                    screen: 'list',
                    dataScope: 'demo',
                    screenKey: 'list',
                    items:
                        scenario === 'refresh window'
                            ? tiles('7d', 1, false).map((item) => ({ ...item, snapshot: () => snapshot }))
                            : [],
                    lists: [
                        {
                            key: 'pins',
                            updatedAt: () => (scenario === 'fresh list' ? Date.now() : 0),
                            refetch,
                        },
                    ],
                    enabled: true,
                }
                const { result, unmount } = renderHook(() => useViewRefresh(props))
                await flush()

                act(() => {
                    result.current.onPull()
                    result.current.onPull()
                })
                await flush()
                expect(result.current.busy).toBe(true)
                expect(result.current.pulling).toBe(true)
                expect(refetch).toHaveBeenCalledTimes(1)
                if (scenario === 'refresh window') {
                    expect(result.current.hint).toBeNull()
                    expect(reads).toEqual(['7d-tile-0'])
                }

                await act(async () => jest.advanceTimersByTime(REFRESH_MIN_MS - 1))
                expect(result.current.busy).toBe(true)
                await act(async () => jest.advanceTimersByTime(1))
                if (finish) {
                    expect(result.current.busy).toBe(true)
                    await act(async () => finish?.())
                }
                expect(result.current.busy).toBe(false)
                expect(result.current.blocked.blocked).toBe(scenario === 'refresh window')
                expect(result.current.pulling).toBe(false)
                unmount()
            } finally {
                jest.useRealTimers()
            }
        }
    )

    test.each<[string, (() => Freshness) | null, boolean, string[]]>([
        [
            'an insight the phone cannot draw gets only cache reads from a pull',
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
            act(() => result.current.onPull())
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

    test.each(
        (['list', 'dashboard'] as const).flatMap((screen) =>
            (['item', 'pull'] as const).flatMap((trigger) =>
                (screen === 'dashboard'
                    ? (['allowed', 'cooling', 'unknown', 'dashboard_floor'] as const)
                    : (['allowed', 'cooling', 'unknown'] as const)
                ).map((window) => ({ screen, trigger, window }))
            )
        )
    )(
        '$screen $trigger refresh reads immediately with a $window server window',
        async ({ screen, trigger, window }) => {
            jest.useFakeTimers()
            try {
                const modes: RefreshMode[] = []
                let snapshot: Freshness = {
                    ...oldValue(),
                    ...(window === 'dashboard_floor' ? { lastRefreshAt: new Date().toISOString() } : {}),
                    cacheTargetAge: new Date(Date.now() + 3_600_000).toISOString(),
                    nextAllowedRefreshAt:
                        window === 'unknown'
                            ? null
                            : new Date(
                                  Date.now() + (window === 'allowed' || window === 'dashboard_floor' ? -60_000 : 60_000)
                              ).toISOString(),
                }
                let containerAt: number | null = null
                const item: RefreshItem = {
                    key: 'insight-manual',
                    family: 'insights',
                    windowMode: 'force_cache',
                    snapshot: () => snapshot,
                    read: async (mode) => {
                        modes.push(mode)
                        snapshot = { ...snapshot, readAt: Date.now() }
                        return { status: 'ok', computed: mode === 'force_blocking' }
                    },
                }
                const props: ViewRefreshOptions = {
                    screen,
                    dataScope: 'https://us.example.com|1',
                    screenKey: screen,
                    items: [item],
                    enabled: true,
                    container:
                        screen === 'dashboard'
                            ? {
                                  key: 'dashboard-manual',
                                  family: 'dashboards',
                                  readAt: () => containerAt,
                                  lastRefresh: () => (window === 'dashboard_floor' ? new Date().toISOString() : null),
                                  read: async () => {
                                      reads.push('dashboard')
                                      containerAt = Date.now()
                                      snapshot = { ...snapshot, readAt: Date.now() }
                                      return { status: 'ok', computed: false }
                                  },
                              }
                            : undefined,
                }
                const { result, unmount } = renderHook(() => useViewRefresh(props))
                await flush()
                modes.length = 0

                act(() => (trigger === 'item' ? result.current.refreshItem(item.key) : result.current.onPull()))
                await flush()
                await act(async () => jest.advanceTimersByTimeAsync(400))

                expect(modes).toEqual(
                    window === 'allowed'
                        ? ['force_blocking']
                        : screen === 'list' || trigger === 'item'
                          ? ['force_cache']
                          : []
                )
                expect(reads).toEqual(
                    screen === 'dashboard' ? (trigger === 'pull' ? ['dashboard', 'dashboard'] : ['dashboard']) : []
                )
                expect(result.current.busy).toBe(false)
                expect(result.current.hint).toBeNull()
                expect(result.current.pulling).toBe(false)
                unmount()
            } finally {
                jest.useRealTimers()
            }
        }
    )

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
        await settle('30d-tile-0')
        await settle('30d-tile-1')
        unmount()
    })

    test.each(['blur', 'disable'] as const)(
        'a dashboard read that finishes after %s cannot enqueue its old tiles when active again',
        async (interruption) => {
            const held = dashboard('blur')
            held.read = read('blur-dashboard', true)
            const old = { ...options('blur', tiles('old', 2, false)), container: held }
            const { rerender, unmount } = renderHook((props: ViewRefreshOptions) => useViewRefresh(props), {
                initialProps: old,
            })
            await flush()
            expect(reads).toEqual(['blur-dashboard'])

            if (interruption === 'blur') {
                mockFocused = false
                rerender(old)
            } else {
                rerender({ ...old, enabled: false })
            }
            await flush()
            if (interruption === 'blur') {
                mockFocused = true
            }
            rerender({ ...old, items: tiles('new', 2, false) })
            await settle('blur-dashboard')

            expect(reads).toEqual(['blur-dashboard', 'new-tile-0', 'new-tile-1'])
            unmount()
        }
    )

    test.each(['uncached', 'metadata only'] as const)(
        'a capped %s read exposes an error that the screen can retry',
        async (state) => {
            const enqueue = jest.spyOn(viewsQueue, 'enqueue').mockResolvedValue({
                status: 'capped',
                computed: false,
                forced: false,
                family: 'insights',
            })
            try {
                const item = tiles(`capped-${state}`, 1, false)[0]
                if (!item) {
                    throw new Error('Expected one tile')
                }
                if (state === 'metadata only') {
                    item.snapshot = () => ({
                        lastRefreshAt: null,
                        cacheTargetAge: null,
                        nextAllowedRefreshAt: null,
                        readAt: Date.now() - 5 * 60_000,
                        refreshFailed: false,
                    })
                }
                const props = { ...options('7d', [item]), container: null }
                const { result, unmount } = renderHook(() => useViewRefresh(props))
                await flush()

                expect(useItemErrors.getState().errors[item.key]).toBe('failed')
                act(() => result.current.retry())
                await flush()
                expect(enqueue).toHaveBeenCalledTimes(2)
                unmount()
            } finally {
                enqueue.mockRestore()
            }
        }
    )
})
