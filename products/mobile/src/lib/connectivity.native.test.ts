import { type NetworkState, NetworkStateType } from 'expo-network'
import { AppState, type AppStateStatus } from 'react-native'

import { monitorConnectivity, useConnectivity } from './connectivity'

jest.mock('expo-network', () => jest.requireActual('expo-network'))
jest.mock('expo-network/build/ExpoNetwork', () => ({
    __esModule: true,
    default: {
        getNetworkStateAsync: jest.fn(),
        addListener: jest.fn(),
    },
}))

const bridge = jest.requireMock('expo-network/build/ExpoNetwork').default as {
    getNetworkStateAsync: jest.Mock<Promise<NetworkState>, []>
    addListener: jest.Mock
}

function state(connected: boolean): NetworkState {
    return {
        type: NetworkStateType.WIFI,
        isConnected: connected,
        isInternetReachable: false,
    }
}

describe('connectivity with the installed Expo Network module', () => {
    let nativeEvent: (state: NetworkState) => void
    let appChange: (state: AppStateStatus) => void
    const originalAppState = AppState.currentState

    beforeEach(() => {
        jest.useFakeTimers()
        AppState.currentState = 'active'
        useConnectivity.setState({ status: 'unknown' })
        bridge.getNetworkStateAsync.mockImplementation(async () => state(true))
        bridge.addListener.mockImplementation((_event, listener) => {
            nativeEvent = listener
            return { remove: jest.fn() }
        })
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
            appChange = listener
            return { remove: jest.fn() }
        })
    })
    afterEach(() => {
        AppState.currentState = originalAppState
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([false, true])(
        'a late refresh reporting %s cannot overwrite a newer native event',
        async (oldConnected) => {
            bridge.getNetworkStateAsync.mockResolvedValueOnce(state(oldConnected))
            const setOnline = jest.fn()
            const stop = monitorConnectivity(setOnline)
            try {
                await jest.advanceTimersByTimeAsync(0)
                expect(useConnectivity.getState().status).toBe(oldConnected ? 'connected' : 'offline')
                let resolve: (state: NetworkState) => void = () => undefined
                bridge.getNetworkStateAsync.mockImplementationOnce(
                    () =>
                        new Promise((yes) => {
                            resolve = yes
                        })
                )
                appChange('background')
                appChange('active')
                const deliveredBefore = setOnline.mock.calls.length
                nativeEvent(state(!oldConnected))
                await jest.advanceTimersByTimeAsync(0)
                resolve(state(oldConnected))
                await jest.advanceTimersByTimeAsync(0)
                expect(useConnectivity.getState().status).toBe(oldConnected ? 'offline' : 'connected')
                expect(setOnline.mock.calls.slice(deliveredBefore)).toEqual([[!oldConnected]])
            } finally {
                stop()
            }
        }
    )

    test('native events remain responsive while refresh is unresolved and cleanup discards the late result', async () => {
        const setOnline = jest.fn()
        const stop = monitorConnectivity(setOnline)
        await jest.advanceTimersByTimeAsync(0)
        let resolve: (state: NetworkState) => void = () => undefined
        bridge.getNetworkStateAsync.mockImplementationOnce(
            () =>
                new Promise((yes) => {
                    resolve = yes
                })
        )
        appChange('background')
        appChange('active')
        nativeEvent(state(false))
        await jest.advanceTimersByTimeAsync(0)
        expect(useConnectivity.getState().status).toBe('offline')
        nativeEvent(state(true))
        await jest.advanceTimersByTimeAsync(0)
        expect(useConnectivity.getState().status).toBe('connected')
        stop()
        const calls = setOnline.mock.calls.length
        resolve(state(false))
        await jest.advanceTimersByTimeAsync(0)
        expect(setOnline).toHaveBeenCalledTimes(calls)
        expect(useConnectivity.getState().status).toBe('connected')
    })
})
