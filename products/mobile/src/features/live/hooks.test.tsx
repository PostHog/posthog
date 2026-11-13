import { act, cleanupAsync, renderHook } from '@testing-library/react-native'
import type { Context, ReactElement, ReactNode } from 'react'

import type { LiveProjectApi } from '@/api/live'
import type { ProjectScope } from '@/api/reports'
import { LIVE_DEMO_READ_MS, LiveDemo } from '@/demo/live'
import { track } from '@/lib/analytics'
import { RECONNECT_NOTICE_DELAY_MS } from '@/lib/useDelayedReconnecting'

import { useLiveFeed, useLiveUsersOnline, useLiveWorld } from './hooks'
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

function pathsEventsAsked(): string[] {
    return mockFetchQuery.mock.calls
        .map(([query]) => query)
        .filter((query) => query.kind === 'TrendsQuery')
        .map((query) => (query.series as { event: string }[])[0]?.event ?? '')
}

describe('useLiveFeed', () => {
    beforeEach(() => {
        mockFocused = true
        liveFocused = true
        mockAppActive = true
        mockMode = 'demo'
        mockScope = null
        jest.useFakeTimers()
    })

    afterEach(async () => {
        await cleanupAsync()
        globalThis.fetch = originalFetch
        clearLiveWorldShare()
        jest.useRealTimers()
        jest.restoreAllMocks()
        jest.clearAllMocks()
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
            act(() => useLiveWorldShare.setState({ world, paused }))
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

    test('app events without pageviews list top screens from the first read, with no pages query', async () => {
        liveProject({ ingested_event: true }, 'app')
        const { result, unmount } = await renderFeed()
        await advance(1000)
        expect(result.current.state).toBe('app_only')
        expect(result.current.snapshot).toMatchObject({
            topPagesMode: 'screens',
            topPages: [
                { label: 'Home', views: 3 },
                { label: 'Settings', views: 1 },
            ],
        })
        expect(pathsEventsAsked()).toEqual(['$screen'])

        await advance(30_000)
        expect(pathsEventsAsked()).toEqual(['$screen', '$screen'])
        unmount()
    })

    test('when pageviews arrive, the next read lists pages without rank badges from the screens', async () => {
        liveProject({ ingested_event: true }, 'app')
        const { result, unmount } = await renderFeed()
        await advance(1000)
        traffic = 'web'
        await advance(30_000)
        expect(pathsEventsAsked()).toEqual(['$screen', '$pageview'])
        expect(result.current.state).toBe('web')
        expect(result.current.snapshot.topPagesMode).toBe('pages')
        expect(result.current.snapshot.topPages?.map((row) => [row.label, row.rankDelta])).toEqual([
            ['Settings', null],
            ['Home', null],
        ])
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
