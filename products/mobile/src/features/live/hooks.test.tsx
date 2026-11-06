import { act, renderHook } from '@testing-library/react-native'

import { LiveDemo } from '@/demo/live'

import { useLiveFeed, useLiveUsersOnline } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-router', () => ({ useIsFocused: () => true }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'demo',
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))
jest.mock('@/features/handoff/useTaskRun', () => ({ useAppActive: () => true }))

async function advance(ms: number): Promise<void> {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

describe('useLiveFeed', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
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
        expect(result.current).toBeNull()

        await advance(65_000)
        expect(result.current).toBeGreaterThan(0)
        expect(respond.mock.calls.map(([key]) => key)).toEqual(['usersOnline', 'usersOnline', 'usersOnline'])
        unmount()
        respond.mockRestore()
    })
})
