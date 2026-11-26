import { act, cleanupAsync, renderHook, waitFor } from '@testing-library/react-native'
import type { Context, ReactElement, ReactNode } from 'react'
import { ApiError } from '@/api/client'
import { type LiveProjectApi, MOBILE_EVENT, WEB_EVENT } from '@/api/live'
import { queryClient } from '@/api/queryClient'
import { persistReadCache } from '@/api/readCache'
import { ReadCacheStore } from '@/api/readCacheStore'
import type { ProjectScope } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import * as tokens from '@/auth/tokens'
import { LIVE_DEMO_READ_MS, LiveDemo } from '@/demo/live'
import { useItemErrors } from '@/features/views/viewsCache'
import { track } from '@/lib/analytics'
import { RECONNECT_NOTICE_DELAY_MS } from '@/lib/useDelayedReconnecting'
import { EMPTY_LIVE_SNAPSHOT } from '@/model/live'
import { DEFAULT_LIVE_TRAFFIC_FILTERS } from '@/model/liveTrafficFilters'

import { useLiveFeed, useLiveUsersOnline, useLiveWorld } from './hooks'
import { useLivePreference } from './livePreference'
import { clearLiveWorldShare, useLiveWorldShare } from './liveWorldStore'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
let mockFocused = true
let mockAppActive = true
let mockMode: 'demo' | 'live' = 'demo'
let mockScope: ProjectScope | null = null
const mockFetchProject = jest.fn<Promise<LiveProjectApi>, []>()
const mockFetchQuery = jest.fn<Promise<unknown>, [Record<string, unknown>]>()
// A hook under `MockFocus` reads its own focus, so a test can blur Live while another screen stays focused.
jest.mock('expo-router', () => {
    const { createContext, useContext } = jest.requireActual<typeof import('react')>('react')
    const MockFocus = createContext<boolean | null>(null)
    return { MockFocus, useIsFocused: () => useContext(MockFocus) ?? mockFocused }
})
const { MockFocus } = jest.requireMock<{ MockFocus: Context<boolean | null> }>('expo-router')
let liveFocused = true

function LiveFocus({ children }: { children: ReactNode }): ReactElement {
    return <MockFocus.Provider value={liveFocused}>{children}</MockFocus.Provider>
}
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => mockMode,
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/features/handoff/useTaskRun', () => ({ useAppActive: () => mockAppActive }))
jest.mock('@/api/live', () => ({
    ...jest.requireActual<typeof import('@/api/live')>('@/api/live'),
    fetchLiveProject: () => mockFetchProject(),
    fetchLiveQuery: (query: Record<string, unknown>) => mockFetchQuery(query),
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

async function advance(ms: number): Promise<void> {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

/** Renders the feed and lets the project read settle, which is what starts the poller. */
async function renderFeed(
    onError: Parameters<typeof useLiveFeed>[0] = () => undefined
): Promise<ReturnType<typeof renderHook<ReturnType<typeof useLiveFeed>, unknown>>> {
    const hook = renderHook(() => useLiveFeed(onError))
    await advance(0)
    return hook
}

/** No events, app events without pageviews, or web traffic. */
type Traffic = 'none' | 'app' | 'web'
let traffic: Traffic = 'none'

// The two forms list the same names in opposite order, so a rank badge carried across forms would show.
const TOP_ROWS: Record<string, unknown[]> = {
    app$screen: [
        { breakdown_value: 'Home', data: [2, 1] },
        { breakdown_value: 'Settings', data: [1] },
    ],
    web$pageview: [
        { breakdown_value: 'Settings', data: [3] },
        { breakdown_value: 'Home', data: [1] },
    ],
}

/** What the server answers for each live query under the current `traffic`. */
function fakeLiveAnswer(query: Record<string, unknown>): unknown {
    if (query.kind === 'TrendsQuery') {
        const event = (query.series as { event: string }[])[0]?.event
        const breakdown = (query.breakdownFilter as { breakdown: string }).breakdown
        const byName = breakdown === (event === '$screen' ? '$screen_name' : '$pathname')
        return { results: byName ? (TOP_ROWS[`${traffic}${event}`] ?? []) : [] }
    }
    const minute = Math.floor(Date.now() / 60_000) * 60_000
    const counts = (app: string, web: string): unknown => ({
        results: [[traffic === 'none' ? [] : [[traffic === 'app' ? app : web, 3]]]],
    })
    const event = traffic === 'app' ? ['e1', '$screen', 'person-1', Date.now(), null, 'Home', null, null] : null
    switch ((query.tags as { name: string }).name) {
        case 'live_mobile_metrics':
            return { results: [[3, 8, 2, 5, 100]] }
        case 'live_mobile_sessions':
            return { results: [[2, 3]] }
        case 'live_screens':
            return {
                results:
                    traffic === 'app'
                        ? [
                              ['Home', 3],
                              ['Settings', 1],
                          ]
                        : [],
            }
        case 'live_users_pageviews':
            return { results: traffic === 'none' ? [] : [[minute, 3, 3, traffic === 'web' ? 4 : 0]] }
        case 'live_device_breakdown':
            return counts('Mobile', 'Desktop')
        case 'live_browser_breakdown':
            return counts('Unknown', 'Chrome')
        case 'live_geo':
            return counts('US', 'US')
        case 'live_recent_events':
            return { results: event ? [event] : [] }
        case 'live_users_count':
            return { results: [[traffic === 'none' ? 0 : 3]] }
        default:
            return { results: [] }
    }
}

let nextProjectId = 1
const SELF_HOSTED = 'https://posthog.example.com'
const CLOUD = 'https://us.posthog.com'

/** A project whose reads go through the fakes. On a self-hosted host, users online come from HogQL. */
function liveProject(project: LiveProjectApi, start: Traffic, host: string = SELF_HOSTED): void {
    mockMode = 'live'
    mockScope = { host, projectId: nextProjectId++ }
    const chosen = renderHook(() => useLivePreference())
    act(() => chosen.result.current.setPreference('web'))
    chosen.unmount()
    traffic = start
    mockFetchProject.mockResolvedValue(project)
    mockFetchQuery.mockImplementation(async (query) => fakeLiveAnswer(query))
}

const originalFetch = globalThis.fetch

/** The live events service's `stats` read, answering as it does for a project with no live users. */
function mockStatsFetch(): jest.Mock {
    const stats = jest.fn(async () => ({ ok: true, json: async () => ({ error: 'no stats' }) }))
    globalThis.fetch = stats as unknown as typeof fetch
    return stats
}

async function refocus(rerender: (props: unknown) => void): Promise<void> {
    mockFocused = false
    rerender({})
    mockFocused = true
    rerender({})
    await advance(0)
}

describe('useLiveFeed', () => {
    test.each([
        { preference: 'all', exclude: false, expectedCount: 91 },
        { preference: 'all', exclude: true, expectedCount: 3 },
        { preference: 'web', exclude: false, expectedCount: 11 },
        { preference: 'mobile', exclude: false, expectedCount: 7 },
    ] as const)(
        'Users online uses the $preference audience (exclude internal: $exclude)',
        async ({ preference, exclude, expectedCount }) => {
            liveProject({ ingested_event: true, live_events_token: 'example-live-token' }, 'web', CLOUD)
            const stats = jest.fn(async () => ({ ok: true, json: async () => ({ users_on_product: 91 }) }))
            globalThis.fetch = stats as unknown as typeof fetch
            const chosen = renderHook(() => useLivePreference())
            act(() => chosen.result.current.setPreference(preference))
            mockFetchQuery.mockImplementation(async (query) => {
                if ((query.tags as { name: string }).name === 'live_users_count') {
                    const text = String(query.query)
                    return { results: [[text.includes(MOBILE_EVENT) ? 7 : text.includes(WEB_EVENT) ? 11 : 3]] }
                }
                return fakeLiveAnswer(query)
            })
            const { result } = renderHook(() => useLiveFeed(() => undefined, exclude))
            await advance(0)
            const useStats = preference === 'all' && !exclude
            expect(result.current.usersOnline).toBe(expectedCount)
            expect(stats.mock.calls.length > 0).toBe(useStats)
            const countQueries = mockFetchQuery.mock.calls.filter(
                ([query]) => (query.tags as { name: string }).name === 'live_users_count'
            )
            expect(countQueries.length > 0).toBe(!useStats)
            if (exclude) {
                expect(countQueries[0]?.[0].filters).toEqual({ filterTestAccounts: true })
            }
        }
    )

    test('changing traffic filters drops old snapshot and hourly metrics and bypasses project-wide stats', async () => {
        liveProject({ ingested_event: true, live_events_token: 'example-live-token' }, 'web', CLOUD)
        const stats = jest.fn(async () => ({ ok: true, json: async () => ({ users_on_product: 91 }) }))
        globalThis.fetch = stats as unknown as typeof fetch
        const selected = renderHook(() => useLivePreference())
        act(() => selected.result.current.setPreference('all'))
        const { result } = await renderFeed()
        expect(result.current.usersOnline).toBe(91)
        expect(result.current.snapshot.mobileMetrics?.dailyActiveUsers).toBe(3)
        stats.mockClear()
        const trafficFilters = {
            ...DEFAULT_LIVE_TRAFFIC_FILTERS,
            channelType: 'Referral',
            deviceType: 'Desktop',
            countryCode: 'CA',
            referringDomain: 'traffic.example.com',
        }
        let finish: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            finish = resolve
        })
        mockFetchQuery.mockImplementation(async (query) => {
            await pending
            switch ((query.tags as { name: string }).name) {
                case 'live_mobile_metrics':
                    return { results: [[0, 0, 0, 0, 0]] }
                case 'live_users_count':
                    return { results: [[1]] }
                default:
                    return fakeLiveAnswer(query)
            }
        })
        act(() => selected.result.current.setLiveFilters('all', trafficFilters))
        expect(result.current.snapshot.activity).toBeNull()
        expect(result.current.snapshot.mobileMetrics ?? null).toBeNull()
        expect(result.current.usersOnline).toBeNull()
        act(() => finish?.())
        await advance(0)
        expect(stats).not.toHaveBeenCalled()
        expect(result.current.usersOnline).toBe(1)
        expect(result.current.snapshot.mobileMetrics?.dailyActiveUsers).toBe(0)
    })

    test('a late response for one hostname never replaces data for the selected hostname', async () => {
        liveProject({ ingested_event: true }, 'web')
        const { result } = renderHook(() => ({ feed: useLiveFeed(() => undefined), selection: useLivePreference() }))
        await advance(0)
        let finish: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            finish = resolve
        })
        mockFetchQuery.mockImplementation(async (query) => {
            const filters = query.filters as { properties?: { key: string; value: string }[] } | undefined
            const hostname = filters?.properties?.find(({ key }) => key === '$host')?.value
            if (hostname === 'first.example.com') await pending
            if ((query.tags as { name: string }).name === 'live_users_count') {
                return { results: [[hostname === 'first.example.com' ? 27 : 4]] }
            }
            return fakeLiveAnswer(query)
        })
        act(() =>
            result.current.selection.setLiveFilters('web', {
                ...DEFAULT_LIVE_TRAFFIC_FILTERS,
                hostname: 'first.example.com',
            })
        )
        await advance(0)
        act(() =>
            result.current.selection.setLiveFilters('web', {
                ...DEFAULT_LIVE_TRAFFIC_FILTERS,
                hostname: 'second.example.com',
            })
        )
        await advance(0)
        expect(result.current.feed.usersOnline).toBe(4)
        act(() => finish?.())
        await advance(0)
        expect(result.current.feed.usersOnline).toBe(4)
    })

    test('switching from All drops an in-flight project-wide count', async () => {
        liveProject({ ingested_event: true, live_events_token: 'example-live-token' }, 'app', CLOUD)
        let finish: ((answer: unknown) => void) | undefined
        globalThis.fetch = jest.fn(
            () =>
                new Promise((resolve) => {
                    finish = resolve
                })
        ) as unknown as typeof fetch
        const { result } = renderHook(() => ({ feed: useLiveFeed(() => undefined), selection: useLivePreference() }))
        act(() => result.current.selection.setPreference('all'))
        await advance(0)
        act(() => result.current.selection.setPreference('mobile'))
        await advance(0)
        act(() => finish?.({ ok: true, json: async () => ({ users_on_product: 91 }) }))
        await advance(0)
        expect(result.current.feed.usersOnline).toBe(3)
    })

    test('a failed audience switch shows a load error and retries the selected audience', async () => {
        liveProject({ ingested_event: true }, 'web')
        const { result } = renderHook(() => ({ feed: useLiveFeed(() => undefined), selection: useLivePreference() }))
        await advance(0)
        expect(result.current.feed.snapshot.activity).not.toBeNull()
        mockFetchQuery.mockRejectedValue(new Error('offline'))
        act(() => result.current.selection.setPreference('mobile'))
        await advance(0)
        expect(result.current.feed.snapshot.activity).toBeNull()
        expect(result.current.feed.loadFailed).toBe(true)
        traffic = 'app'
        mockFetchQuery.mockImplementation(async (query) => fakeLiveAnswer(query))
        act(() => result.current.feed.retry())
        await advance(0)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mobile')
        expect(result.current.feed.snapshot.activity).not.toBeNull()
        expect(result.current.feed.loadFailed).toBe(false)
    })

    test('live activity and sessions load before the slow mobile metrics finish', async () => {
        liveProject({ ingested_event: true }, 'app')
        const chosen = renderHook(() => useLivePreference())
        act(() => chosen.result.current.setPreference('all'))
        let finish: ((answer: unknown) => void) | undefined
        mockFetchQuery.mockImplementation((query) =>
            (query.tags as { name: string }).name === 'live_mobile_metrics'
                ? new Promise((resolve) => {
                      finish = resolve
                  })
                : Promise.resolve(fakeLiveAnswer(query))
        )
        const { result } = await renderFeed()
        await advance(0)
        expect(result.current.snapshot.activity).not.toBeNull()
        expect(result.current.snapshot.mobileMetrics?.sessions).toBe(2)
        expect(result.current.snapshot.mobileMetrics?.dailyActiveUsers).toBeNull()
        act(() => finish?.({ results: [[3, 8, 2, 5, 100]] }))
        await advance(0)
        expect(result.current.snapshot.mobileMetrics?.dailyActiveUsers).toBe(3)
        expect(result.current.snapshot.mobileMetrics?.sessions).toBe(2)
    })

    test('failed slow refreshes retain metrics, warn, and recover through retry', async () => {
        liveProject({ ingested_event: true }, 'app')
        const chosen = renderHook(() => useLivePreference())
        act(() => chosen.result.current.setPreference('all'))
        const { result } = await renderFeed()
        await advance(0)
        const before = result.current.snapshot.mobileMetrics
        expect(before?.dailyActiveUsers).toBe(3)
        mockFetchQuery.mockImplementation(async (query) => {
            if ((query.tags as { name: string }).name === 'live_mobile_metrics') throw new Error('offline')
            return fakeLiveAnswer(query)
        })
        await advance(60 * 60_000)
        await advance(RECONNECT_NOTICE_DELAY_MS)
        expect(result.current.snapshot.mobileMetrics?.dailyActiveUsers).toBe(3)
        expect(result.current.snapshot.mobileMetrics?.updatedAt).toBe(before?.updatedAt)
        expect(result.current.status).toBe('reconnecting')
        mockFetchQuery.mockImplementation(async (query) => fakeLiveAnswer(query))
        await advance(60_000)
        act(() => result.current.retry())
        await advance(0)
        expect(result.current.status).toBe('live')
        expect(result.current.snapshot.mobileMetrics?.updatedAt).toBeGreaterThan(before?.updatedAt ?? 0)
    })

    test('an audience selected during a read starts immediately after the old read finishes', async () => {
        const { result } = renderHook(() => ({ feed: useLiveFeed(() => undefined), preference: useLivePreference() }))
        await advance(0)
        await advance(LIVE_DEMO_READ_MS)
        expect(result.current.feed.reading).toBe(true)
        act(() => result.current.preference.setPreference('mobile'))
        await advance(5000)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mobile')
        expect(result.current.feed.snapshot.activity).not.toBeNull()
        act(() => result.current.preference.setPreference('all'))
        await advance(5000)
    })

    test('switching audience while paused waits for resume and All hides the previous mode', async () => {
        jest.useFakeTimers()
        const respond = jest.spyOn(LiveDemo.prototype, 'respond')
        const { result } = renderHook(() => ({ feed: useLiveFeed(() => undefined), preference: useLivePreference() }))
        await advance(0)
        await advance(5000)
        act(() => result.current.feed.pause())
        respond.mockClear()
        act(() => result.current.preference.setPreference('mobile'))
        await advance(60000)
        expect(result.current.feed.paused).toBe(true)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mobile')
        expect(result.current.feed.snapshot.activity).toBeNull()
        expect(respond).not.toHaveBeenCalled()
        act(() => result.current.feed.resume())
        await advance(5000)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mobile')
        expect(result.current.feed.snapshot.activity).not.toBeNull()
        act(() => result.current.feed.pause())
        respond.mockClear()
        act(() => result.current.preference.setPreference('all'))
        await advance(60000)
        expect(result.current.feed.paused).toBe(true)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mixed')
        expect(result.current.feed.snapshot.activity).toBeNull()
        expect(respond).not.toHaveBeenCalled()
        act(() => result.current.feed.resume())
        await advance(5000)
        expect(result.current.feed.snapshot.profile?.kind).toBe('mixed')
    })

    beforeEach(() => {
        queryClient.clear()
        useAuthStore.setState({
            user: { uuid: 'test-user', distinctId: 'test-user', email: 'test@example.com', name: 'Test Account' },
        })
        useItemErrors.getState().reset()
        mockFocused = true
        liveFocused = true
        mockAppActive = true
        mockMode = 'demo'
        mockScope = null
        jest.useFakeTimers()
        const chosen = renderHook(() => useLivePreference())
        act(() => chosen.result.current.setLiveFilters('web', DEFAULT_LIVE_TRAFFIC_FILTERS))
        chosen.unmount()
    })

    afterEach(async () => {
        await cleanupAsync()
        globalThis.fetch = originalFetch
        clearLiveWorldShare()
        jest.useRealTimers()
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    test('reopening keeps the last values while refreshing and after a failed refresh', async () => {
        const first = await renderFeed()
        await advance(5000)
        const previous = first.result.current.snapshot
        const previousReadAt = first.result.current.updatedAt
        expect(previousReadAt).not.toBeNull()
        first.unmount()
        const respond = jest.spyOn(LiveDemo.prototype, 'respond').mockImplementation(() => {
            throw new Error('Offline')
        })
        const reopened = await renderFeed()
        expect(reopened.result.current.reading).toBe(true)
        expect(reopened.result.current.snapshot.activity).toEqual(previous.activity)
        expect(reopened.result.current.snapshot.world).toEqual(previous.world)
        await advance(5000)
        expect(reopened.result.current.loadFailed).toBe(false)
        expect(reopened.result.current.snapshot.activity).toEqual(previous.activity)
        expect(reopened.result.current.updatedAt).toBe(previousReadAt)
        respond.mockRestore()
        act(() => reopened.result.current.retry())
        await advance(5000)
        expect(reopened.result.current.reading).toBe(false)
        expect(reopened.result.current.status).toBe('live')
        expect(reopened.result.current.updatedAt).toBeGreaterThan(previousReadAt ?? 0)
    })

    test('a read keeps a map restored while its queries were already in flight', async () => {
        liveProject({ ingested_event: true }, 'web')
        const initial = await renderFeed()
        const previous = initial.result.current.snapshot
        initial.unmount()
        queryClient.clear()
        let release: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            release = resolve
        })
        mockFetchQuery.mockImplementation(async (query) => {
            await pending
            if ((query.tags as { name: string }).name === 'live_geo') throw new Error('Offline')
            return fakeLiveAnswer(query)
        })
        const reopened = await renderFeed()
        act(() =>
            queryClient.setQueryData(['views', mockScope?.host, mockScope?.projectId, 'live', 'web'], {
                snapshot: previous,
                dataReadAt: Date.now() - 60_000,
            })
        )
        await advance(0)
        expect(reopened.result.current.snapshot.world).toEqual(previous.world)
        act(() => release?.())
        await advance(0)
        expect(reopened.result.current.snapshot.world).toEqual(previous.world)
        reopened.unmount()
        const again = await renderFeed()
        expect(again.result.current.snapshot.world).toEqual(previous.world)
    })

    test.each([
        [401, 'query'],
        [403, 'query'],
        [404, 'query'],
        [403, 'project'],
        [404, 'project'],
    ] as const)('denial %s from %s removes every saved audience and active values', async (status, endpoint) => {
        liveProject({ ingested_event: true }, 'web')
        if (!mockScope) throw new Error('The test requires a project.')
        const scope = { ...mockScope, account: 'invented-cache-account' }
        const values = new Map<string, string>()
        const store = new ReadCacheStore({
            getItem: async (key) => values.get(key) ?? null,
            setItem: async (key, value) => {
                values.set(key, value)
            },
            removeItem: async (key) => {
                values.delete(key)
            },
        })
        const denied = (key: readonly unknown[]): boolean =>
            useItemErrors.getState().errors[JSON.stringify(key)] === 'no_access'
        const persisted = persistReadCache(queryClient, store, scope, () => true, denied)
        const unsubscribe = useItemErrors.subscribe(() => persisted.purgeDeniedViews())
        await persisted.ready
        const first = endpoint === 'query' ? await renderFeed() : null
        const previous = first?.result.current.snapshot ?? { ...EMPTY_LIVE_SNAPSHOT, usersOnline: 17 }
        for (const preference of ['all', 'web', 'mobile'] as const) {
            queryClient.setQueryData(['views', scope.host, scope.projectId, 'live', preference], {
                snapshot: { ...previous, preference },
                dataReadAt: Date.now(),
            })
        }
        await persisted.flush()
        expect(await store.load(scope)).toHaveLength(3)
        const error = new ApiError(status, { detail: 'No access' })
        if (endpoint === 'project') mockFetchProject.mockRejectedValue(error)
        const hook = first ?? (await renderFeed())
        if (endpoint === 'query') {
            mockFetchQuery.mockImplementation(async (query) => {
                if ((query.tags as { name: string }).name === 'live_geo') throw error
                return fakeLiveAnswer(query)
            })
            act(() => hook.result.current.retry())
        }
        await advance(0)
        expect(hook.result.current.snapshot.activity).toBeNull()
        expect(hook.result.current.snapshot.world).toBeNull()
        expect(hook.result.current.usersOnline).toBeNull()
        expect(hook.result.current.loadFailed).toBe(true)
        expect(hook.result.current.reading).toBe(false)
        await persisted.flush()
        expect(await store.load(scope)).toEqual([])
        for (const preference of ['all', 'web', 'mobile']) {
            expect(queryClient.getQueryData(['views', scope.host, scope.projectId, 'live', preference])).toBeUndefined()
        }
        mockFetchProject.mockResolvedValue({ ingested_event: true })
        mockFetchQuery.mockImplementation(async (query) => fakeLiveAnswer(query))
        act(() => hook.result.current.retry())
        await advance(0)
        expect(hook.result.current.snapshot.activity).not.toBeNull()
        expect(hook.result.current.loadFailed).toBe(false)
        unsubscribe()
        persisted.stop()
    })

    test('a denial settling after sign-out cannot purge the next session cache', async () => {
        let generation = 100
        jest.spyOn(tokens, 'sessionGeneration').mockImplementation(() => generation)
        liveProject({ ingested_event: true }, 'web')
        const first = await renderFeed()
        let reject: ((error: Error) => void) | undefined
        const pending = new Promise((_resolve, fail) => {
            reject = fail
        })
        mockFetchQuery.mockImplementation(() => pending)
        act(() => first.result.current.retry())
        await advance(0)
        first.unmount()
        generation++
        const key = ['views', mockScope?.host, mockScope?.projectId, 'live', 'web']
        const next = {
            snapshot: { ...EMPTY_LIVE_SNAPSHOT, preference: 'web', usersOnline: 42 },
            dataReadAt: Date.now(),
        }
        act(() => queryClient.setQueryData(key, next))
        act(() => reject?.(new ApiError(403, { detail: 'No access' })))
        await advance(0)
        expect(queryClient.getQueryData(key)).toEqual(next)
        expect(useItemErrors.getState().errors[JSON.stringify(key)]).toBeUndefined()
    })

    test('restored data appears while the project request is still pending and stays scoped to its audience', async () => {
        mockMode = 'live'
        mockScope = { host: 'https://example.com', projectId: 55 }
        mockFetchProject.mockImplementation(() => new Promise(() => undefined))
        const saved = { ...EMPTY_LIVE_SNAPSHOT, preference: 'all' as const, usersOnline: 17 }
        const hook = await renderFeed()
        expect(hook.result.current.snapshot.usersOnline).toBeNull()
        act(() =>
            queryClient.setQueryData(['views', mockScope?.host, 55, 'live', 'all'], {
                snapshot: saved,
                dataReadAt: Date.now() - 60000,
            })
        )
        await advance(0)
        await waitFor(() => expect(hook.result.current.usersOnline).toBe(17))
        expect(hook.result.current.reading).toBe(true)
        const preference = renderHook(() => useLivePreference())
        act(() => preference.result.current.setPreference('mobile'))
        await advance(0)
        expect(hook.result.current.usersOnline).toBeNull()
    })

    test('demo mode fills every card, counts users online with HogQL, and reads nothing while paused', async () => {
        const { result, unmount } = await renderFeed()
        expect(result.current.status).toBe('loading')

        await advance(5000)
        const { snapshot, updatedAt } = result.current
        expect(result.current.status).toBe('live')
        expect(snapshot.activity?.minutes).toHaveLength(30)
        expect(snapshot.topPages?.length).toBeGreaterThan(0)
        expect(snapshot.topReferrers?.length).toBeGreaterThan(0)
        expect(snapshot.devices?.rows.length).toBeGreaterThan(0)
        expect(snapshot.events?.length).toBeGreaterThan(0)
        expect(result.current.usersOnline).toBeGreaterThan(0)

        act(() => result.current.pause())
        await advance(5 * 60_000)
        expect(result.current.status).toBe('paused')
        expect(result.current.updatedAt).toBe(updatedAt)

        act(() => result.current.resume())
        await advance(5000)
        expect(result.current.status).toBe('live')
        expect(result.current.updatedAt).not.toBe(updatedAt)
        unmount()
    })

    test.each([
        ['live', false, ['geo', 'geo', 'geo']],
        ['paused', true, []],
    ] as const)(
        'with Visitors by country focused and Live %s, Live sends nothing and the screen sends only geo reads',
        async (status, paused, keys) => {
            const live = renderHook(() => useLiveFeed(() => undefined), { wrapper: LiveFocus })
            await advance(0)
            await advance(5000)
            if (paused) {
                act(() => live.result.current.pause())
            }
            const { world } = live.result.current.snapshot
            // The map card shares Live's countries and Pause as it pushes the screen, which takes Live's focus.
            act(() => useLiveWorldShare.setState({ world, paused, webOnly: true }))
            liveFocused = false
            live.rerender({})
            const respond = jest.spyOn(LiveDemo.prototype, 'respond')
            const countries = renderHook(() => useLiveWorld())
            expect(countries.result.current).toMatchObject({ status, world })

            await advance(65_000)
            expect(respond.mock.calls.map(([key]) => key)).toEqual(keys)
            expect(countries.result.current.status).toBe(status)
            countries.unmount()
            live.unmount()
        }
    )

    test.each(['web', 'mobile'] as const)(
        'country retry keeps its %s audience after access denial',
        async (audience) => {
            liveProject({ ingested_event: true }, 'web')
            if (!mockScope) throw new Error('The test requires a project.')
            jest.spyOn(useAuthStore, 'getState').mockReturnValue({ ...useAuthStore.getState(), ...mockScope })
            const selected = renderHook(() => useLivePreference())
            const trafficFilters = {
                ...DEFAULT_LIVE_TRAFFIC_FILTERS,
                excludeBots: true,
                countryCode: 'US',
                deviceType: 'Mobile',
                channelType: 'Organic Search',
                referringDomain: 'google.com',
            }
            act(() => selected.result.current.setLiveFilters(audience, trafficFilters))
            act(() =>
                useLiveWorldShare.setState({
                    world: null,
                    paused: false,
                    trafficFilters,
                    users: audience === 'mobile',
                    webOnly: audience === 'web',
                    mobileOnly: audience === 'mobile',
                })
            )
            const countries = renderHook(() => useLiveWorld())
            await advance(0)
            expect(countries.result.current.world?.total).toBe(3)
            mockFetchQuery.mockRejectedValue(new ApiError(403, { detail: 'No access' }))
            act(() => countries.result.current.retry())
            await advance(0)
            expect(countries.result.current.loadFailed).toBe(true)
            expect(countries.result.current.world).toBeNull()
            mockFetchQuery.mockImplementation(async (query) => fakeLiveAnswer(query))
            mockFetchQuery.mockClear()
            act(() => countries.result.current.retry())
            await advance(0)
            expect(countries.result.current.loadFailed).toBe(false)
            expect(countries.result.current.world?.total).toBe(3)
            expect(mockFetchQuery.mock.calls.map(([query]) => query.query)).toEqual([
                expect.stringContaining(audience === 'web' ? WEB_EVENT : MOBILE_EVENT),
            ])
            expect(mockFetchQuery.mock.calls[0]?.[0].filters).toEqual(
                expect.objectContaining({
                    properties: expect.arrayContaining([
                        expect.objectContaining({ key: '$virt_is_bot' }),
                        expect.objectContaining({ key: '$geoip_country_code', value: 'US' }),
                        expect.objectContaining({ key: '$device_type', value: 'Mobile' }),
                        expect.objectContaining({ key: '$channel_type', type: 'session', value: 'Organic Search' }),
                        expect.objectContaining({
                            key: '$entry_referring_domain',
                            type: 'session',
                            value: 'google.com',
                        }),
                    ]),
                })
            )
            expect(useLiveWorldShare.getState().users).toBe(audience === 'mobile')
        }
    )

    test('the Live chip counts users online alone, once every 30 seconds', async () => {
        const respond = jest.spyOn(LiveDemo.prototype, 'respond')
        const { result, unmount } = renderHook(() => useLiveUsersOnline())
        expect(result.current).toMatchObject({ count: null, reconnecting: false })

        await advance(65_000)
        expect(result.current.count).toBeGreaterThan(0)
        expect(respond.mock.calls.map(([key]) => key)).toEqual(['usersOnline', 'usersOnline', 'usersOnline'])
        unmount()
    })

    test.each([false, true])('the Live chip verifies recovery before warning (still failing: %s)', async (failing) => {
        const respond = jest.spyOn(LiveDemo.prototype, 'respond')
        const { result } = renderHook(() => useLiveUsersOnline())
        await advance(LIVE_DEMO_READ_MS)
        const count = result.current.count
        expect(count).toBeGreaterThan(0)

        respond.mockImplementationOnce(() => {
            throw new Error('Live unavailable')
        })
        await advance(30_000 + LIVE_DEMO_READ_MS)
        expect(result.current).toMatchObject({ count, reconnecting: false })
        if (failing) {
            respond.mockImplementationOnce(() => {
                throw new Error('Live unavailable')
            })
        }
        await advance(RECONNECT_NOTICE_DELAY_MS - 1)
        expect(result.current).toMatchObject({ count, reconnecting: false })
        await advance(1)
        expect(result.current).toMatchObject({ count, reconnecting: false })
        await advance(LIVE_DEMO_READ_MS)
        expect(result.current.reconnecting).toBe(failing)
        expect(result.current.count === null).toBe(failing)

        await advance((failing ? 60_000 : 30_000) + LIVE_DEMO_READ_MS)
        expect(result.current.reconnecting).toBe(false)
        expect(result.current.count).toBeGreaterThan(0)
    })

    test.each(['partial', 'total'] as const)(
        'the Live screen delays a %s refresh warning and cancels it on recovery',
        async (failure) => {
            const original = LiveDemo.prototype.respond
            const respond = jest.spyOn(LiveDemo.prototype, 'respond')
            const onError = jest.fn()
            const { result } = await renderFeed(onError)
            await advance(LIVE_DEMO_READ_MS * 4)
            expect(result.current.status).toBe('live')

            const fail = (): void => {
                respond.mockImplementation(function (this: LiveDemo, key, now) {
                    if (failure === 'total' || key === 'usersPageviews') throw new Error('Live unavailable')
                    return original.call(this, key, now)
                })
            }
            fail()
            act(() => result.current.pull())
            await advance(LIVE_DEMO_READ_MS * 4)
            expect(result.current.status).toBe('live')
            expect(onError).not.toHaveBeenCalled()
            await advance(RECONNECT_NOTICE_DELAY_MS - 1)
            expect(result.current.status).toBe('live')
            await advance(1)
            expect(result.current.status).toBe('live')
            expect(onError).not.toHaveBeenCalled()
            await advance(LIVE_DEMO_READ_MS * 4)
            expect(result.current.status).toBe('reconnecting')
            expect(onError).toHaveBeenCalledTimes(1)
            expect(onError).toHaveBeenLastCalledWith('refresh_failed')
            act(() => result.current.pause())
            act(() => result.current.resume())
            await advance(LIVE_DEMO_READ_MS * 4 + RECONNECT_NOTICE_DELAY_MS)
            expect(onError).toHaveBeenCalledTimes(1)

            respond.mockImplementation(original)
            act(() => result.current.pull())
            await advance(LIVE_DEMO_READ_MS * 4)
            expect(result.current.status).toBe('live')

            fail()
            act(() => result.current.pull())
            await advance(LIVE_DEMO_READ_MS * 4)
            respond.mockImplementation(original)
            await advance(RECONNECT_NOTICE_DELAY_MS + LIVE_DEMO_READ_MS * 4)
            expect(result.current.status).toBe('live')
            expect(onError).toHaveBeenCalledTimes(1)
        }
    )

    test.each(['active', 'tab blur', 'app background'])(
        'recovery verification joins an in-flight refresh or cancels when hidden (%s)',
        async (visibility) => {
            const original = LiveDemo.prototype.respond
            const respond = jest.spyOn(LiveDemo.prototype, 'respond')
            const onError = jest.fn()
            const { result, rerender } = await renderFeed(onError)
            await advance(LIVE_DEMO_READ_MS * 4)
            const readKeys = respond.mock.calls.map(([key]) => key)
            respond.mockImplementation(() => {
                throw new Error('Live unavailable')
            })
            act(() => result.current.pull())
            await advance(LIVE_DEMO_READ_MS * 4)
            await advance(RECONNECT_NOTICE_DELAY_MS - 1)
            respond.mockImplementation(original)
            const beforeRefresh = respond.mock.calls.length
            act(() => result.current.pull())
            mockFocused = visibility !== 'tab blur'
            mockAppActive = visibility !== 'app background'
            rerender({})
            await advance(LIVE_DEMO_READ_MS * 4 + RECONNECT_NOTICE_DELAY_MS)
            expect(result.current.status).toBe('live')
            expect(onError).not.toHaveBeenCalled()
            expect(respond.mock.calls.slice(beforeRefresh).map(([key]) => key)).toEqual(
                visibility === 'tab blur' ? [] : readKeys
            )
        }
    )

    test('a window without events reads as quiet, says so once per focus, keeps polling, and pauses stats', async () => {
        const stats = mockStatsFetch()
        liveProject({ ingested_event: true, live_events_token: 'example-live-token' }, 'none', CLOUD)
        const { result, unmount } = await renderFeed()
        await advance(1000)
        expect(result.current.state).toBe('quiet')

        const asked = mockFetchQuery.mock.calls.length
        const statsReads = stats.mock.calls.length
        await advance(30_000)
        expect(mockFetchQuery.mock.calls.length).toBeGreaterThan(asked)
        expect(stats.mock.calls.length).toBe(statsReads)
        expect(result.current.state).toBe('quiet')
        expect(jest.mocked(track).mock.calls.filter(([event]) => event === 'mobile_live_state_shown')).toEqual([
            ['mobile_live_state_shown', { state: 'quiet' }],
        ])
        unmount()
    })

    test('All keeps separate page and screen lists without changing audience when traffic changes', async () => {
        liveProject({ ingested_event: true }, 'app')
        const chosen = renderHook(() => useLivePreference())
        act(() => chosen.result.current.setPreference('all'))
        const { result, unmount } = await renderFeed()
        await advance(1000)
        expect(result.current.snapshot.profile?.kind).toBe('mixed')
        expect(result.current.snapshot.topPagesMode).toBe('pages')
        expect(result.current.snapshot.topScreens?.map((row) => row.label)).toEqual(['Home', 'Settings'])
        traffic = 'web'
        await advance(30_000)
        expect(result.current.snapshot.profile?.kind).toBe('mixed')
        expect(result.current.snapshot.topPages?.map((row) => row.label)).toEqual(['Settings', 'Home'])
        expect(chosen.result.current.preference).toBe('all')
        unmount()
    })

    test('a project without events runs no jobs or stats reads and reads the project once a minute while seen', async () => {
        const stats = mockStatsFetch()
        liveProject({ ingested_event: false, live_events_token: 'example-live-token' }, 'none', CLOUD)
        const { result, rerender, unmount } = await renderFeed()
        expect(result.current.state).toBe('not_set_up')
        await advance(3 * 60_000)
        expect(mockFetchProject).toHaveBeenCalledTimes(4)
        expect(mockFetchQuery).not.toHaveBeenCalled()
        expect(stats).not.toHaveBeenCalled()

        await refocus(rerender)
        expect(mockFetchProject).toHaveBeenCalledTimes(4)

        mockFetchProject.mockResolvedValue({ ingested_event: true, live_events_token: 'example-live-token' })
        await advance(60_000)
        await advance(1000)
        expect(mockFetchProject).toHaveBeenCalledTimes(5)
        expect(mockFetchQuery).toHaveBeenCalled()
        expect(result.current.state).toBe('quiet')
        unmount()
    })

    test('a failed project re-read keeps Not set up and waits out the minute', async () => {
        liveProject({ ingested_event: false }, 'none')
        const { result, rerender, unmount } = await renderFeed()
        mockFetchProject.mockRejectedValueOnce(new Error('offline'))
        await advance(60_000)
        expect(mockFetchProject).toHaveBeenCalledTimes(2)
        expect(result.current.state).toBe('not_set_up')

        await refocus(rerender)
        expect(mockFetchProject).toHaveBeenCalledTimes(2)
        expect(mockFetchQuery).not.toHaveBeenCalled()
        unmount()
    })

    test('unknown project metadata recovers while Live stays open and stops reads for an unconfigured project', async () => {
        const stats = mockStatsFetch()
        liveProject({ ingested_event: false, live_events_token: 'example-live-token' }, 'none', CLOUD)
        mockFetchProject.mockRejectedValue(new Error('offline'))
        const { result, unmount } = await renderFeed()
        await advance(1000)
        expect(result.current.state).toBe('quiet')

        mockFetchProject.mockResolvedValue({ ingested_event: false, live_events_token: 'example-live-token' })
        await advance(30_000)
        expect(result.current.state).toBe('quiet')

        await advance(30_000)
        expect(result.current.state).toBe('not_set_up')
        const queries = mockFetchQuery.mock.calls.length
        await advance(2 * 60_000)
        expect(mockFetchQuery).toHaveBeenCalledTimes(queries)
        expect(stats).not.toHaveBeenCalled()
        unmount()
    })

    test('a pull on Not set up reads the project at once and starts polling when it has an event', async () => {
        liveProject({ ingested_event: false }, 'none')
        const { result, unmount } = await renderFeed()
        mockFetchProject.mockResolvedValue({ ingested_event: true })
        act(() => result.current.pull())
        await advance(1000)
        expect(mockFetchProject).toHaveBeenCalledTimes(2)
        expect(mockFetchQuery).toHaveBeenCalled()
        expect(result.current.state).toBe('quiet')
        unmount()
    })

    test.each(['tab blur', 'app background'])(
        'disables Live visual updates on %s and reenables them on return',
        async (event) => {
            const { result, rerender } = renderHook(() => ({
                feed: useLiveFeed(() => undefined).screenActive,
                chip: useLiveUsersOnline().screenActive,
            }))
            await advance(0)
            expect(result.current).toEqual({ feed: true, chip: true })

            mockFocused = event !== 'tab blur'
            mockAppActive = event !== 'app background'
            rerender({})
            expect(result.current).toEqual({ feed: false, chip: false })

            mockFocused = true
            mockAppActive = true
            rerender({})
            expect(result.current).toEqual({ feed: true, chip: true })
        }
    )
})
