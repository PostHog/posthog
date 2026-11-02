import NetInfo, { type NetInfoState } from '@react-native-community/netinfo'
import { onlineManager, QueryClient, QueryObserver } from '@tanstack/react-query'
import { AppState, type AppStateStatus } from 'react-native'
import { monitorConnectivity, useConnectivity } from './connectivity'

function state(isConnected: boolean | null, expensive = false): NetInfoState {
    return {
        type: 'wifi',
        isConnected,
        isInternetReachable: false,
        details: { isConnectionExpensive: expensive },
    } as NetInfoState
}

describe('connectivity', () => {
    let update: (state: NetInfoState) => void
    let changeAppState: (state: AppStateStatus) => void
    let unsubscribe: jest.Mock
    let remove: jest.Mock
    const originalAppState = AppState.currentState
    beforeEach(() => {
        jest.useFakeTimers()
        AppState.currentState = 'active'
        useConnectivity.setState({ status: 'unknown', isConnectionExpensive: null })
        unsubscribe = jest.fn()
        remove = jest.fn()
        jest.mocked(NetInfo.addEventListener).mockImplementation((listener) => {
            update = listener
            return unsubscribe
        })
        jest.mocked(NetInfo.refresh)
            .mockClear()
            .mockImplementation(() => new Promise(() => undefined))
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
            changeAppState = listener
            return { remove }
        })
    })
    afterEach(() => {
        AppState.currentState = originalAppState
        jest.restoreAllMocks()
        onlineManager.setEventListener(() => undefined)
        onlineManager.setOnline(true)
        jest.useRealTimers()
    })
    test('unknown allows reads, offline pauses them, and reconnect resumes one request', async () => {
        onlineManager.setEventListener(monitorConnectivity)
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        client.mount()
        const fetch = jest.fn(async () => 'loaded')
        const observer = new QueryObserver(client, { queryKey: ['connectivity-read'], queryFn: fetch })
        update(state(false))
        await jest.advanceTimersByTimeAsync(0)
        const stop = observer.subscribe(() => undefined)
        expect(observer.getCurrentResult().fetchStatus).toBe('paused')
        expect(fetch).not.toHaveBeenCalled()
        update(state(null))
        await jest.advanceTimersByTimeAsync(0)
        expect(observer.getCurrentResult().data).toBe('loaded')
        expect(fetch).toHaveBeenCalledTimes(1)
        expect(useConnectivity.getState().status).toBe('unknown')
        update(state(true, true))
        await jest.advanceTimersByTimeAsync(0)
        expect(useConnectivity.getState()).toEqual({ status: 'connected', isConnectionExpensive: true })
        stop()
        client.unmount()
        client.clear()
        expect(unsubscribe).toHaveBeenCalledTimes(1)
        expect(remove).toHaveBeenCalledTimes(1)
    })
    test.each(['success', 'failure'] as const)(
        'foreground refresh %s preserves newer events and cleanup stops late updates',
        async (outcome) => {
            let resolve: (state: NetInfoState) => void = () => undefined
            let reject: (error: Error) => void = () => undefined
            jest.mocked(NetInfo.refresh)
                .mockResolvedValueOnce(state(true))
                .mockImplementationOnce(
                    () =>
                        new Promise((yes, no) => {
                            resolve = yes
                            reject = no
                        })
                )
            const setOnline = jest.fn()
            const stop = monitorConnectivity(setOnline)
            await Promise.resolve()
            await Promise.resolve()
            await Promise.resolve()
            changeAppState('background')
            changeAppState('active')
            changeAppState('active')
            expect(NetInfo.refresh).toHaveBeenCalledTimes(2)
            update(state(false))
            if (outcome === 'success') resolve(state(true))
            else reject(new Error('Native state unavailable'))
            await jest.advanceTimersByTimeAsync(0)
            expect(useConnectivity.getState().status).toBe('offline')
            stop()
            update(state(true))
            expect(useConnectivity.getState().status).toBe('offline')
            expect(setOnline).toHaveBeenLastCalledWith(false)
        }
    )
})
