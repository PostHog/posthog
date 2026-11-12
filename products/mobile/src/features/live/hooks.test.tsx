import { act, cleanup, renderHook } from '@testing-library/react-native'

import { LIVE_DEMO_READ_MS, LiveDemo } from '@/demo/live'
import { RECONNECT_NOTICE_DELAY_MS } from '@/lib/useDelayedReconnecting'

import { useLiveFeed, useLiveUsersOnline } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
let mockFocused = true
let mockAppActive = true
jest.mock('expo-router', () => ({ useIsFocused: () => mockFocused }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'demo',
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))
jest.mock('@/features/handoff/useTaskRun', () => ({ useAppActive: () => mockAppActive }))

async function advance(ms: number): Promise<void> {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

describe('useLiveFeed', () => {
    beforeEach(() => {
        mockFocused = true
        mockAppActive = true
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    test('demo mode fills every card, counts users online with HogQL, and reads nothing while paused', async () => {
        const { result, unmount } = renderHook(() => useLiveFeed(() => undefined))
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
            const { result } = renderHook(() => useLiveFeed(onError))
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
            const { result, rerender } = renderHook(() => useLiveFeed(onError))
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

    test.each(['tab blur', 'app background'])(
        'disables Live visual updates on %s and reenables them on return',
        (event) => {
            const { result, rerender } = renderHook(() => ({
                feed: useLiveFeed(() => undefined).screenActive,
                chip: useLiveUsersOnline().screenActive,
            }))
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
