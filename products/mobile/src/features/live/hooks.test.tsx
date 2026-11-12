import { act, renderHook } from '@testing-library/react-native'

import { LIVE_DEMO_READ_MS, LiveDemo } from '@/demo/live'

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

    test('the Live chip drops a stale count until a poll succeeds again', async () => {
        const respond = jest.spyOn(LiveDemo.prototype, 'respond')
        const { result } = renderHook(() => useLiveUsersOnline())
        await advance(LIVE_DEMO_READ_MS)
        expect(result.current.count).toBeGreaterThan(0)

        respond.mockImplementationOnce(() => {
            throw new Error('Live unavailable')
        })
        await advance(30_000 + LIVE_DEMO_READ_MS)
        expect(result.current).toMatchObject({ count: null, reconnecting: true })

        await advance(30_000 + LIVE_DEMO_READ_MS)
        expect(result.current.reconnecting).toBe(false)
        expect(result.current.count).toBeGreaterThan(0)
    })

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
