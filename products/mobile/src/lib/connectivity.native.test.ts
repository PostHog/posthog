import NetInfo, { type NetInfoState } from '@react-native-community/netinfo'
import { AppState, type AppStateStatus } from 'react-native'

import { monitorConnectivity, useConnectivity } from './connectivity'

jest.mock('@react-native-community/netinfo', () => jest.requireActual('@react-native-community/netinfo/src/index'))
jest.mock('@react-native-community/netinfo/src/internal/nativeInterface', () => ({
    __esModule: true,
    default: {
        configure: jest.fn(),
        getCurrentState: jest.fn(),
        eventEmitter: { addListener: jest.fn() },
    },
}))

const bridge = jest.requireMock('@react-native-community/netinfo/src/internal/nativeInterface').default as {
    getCurrentState: jest.Mock<Promise<NetInfoState>, []>
    eventEmitter: { addListener: jest.Mock }
}

function state(connected: boolean): NetInfoState {
    return {
        type: 'wifi',
        isConnected: connected,
        isInternetReachable: false,
        details: { isConnectionExpensive: false },
    } as NetInfoState
}

describe('connectivity with the installed NetInfo state manager', () => {
    let nativeEvent: (state: NetInfoState) => void
    let appChange: (state: AppStateStatus) => void

    beforeEach(() => {
        jest.useFakeTimers()
        AppState.currentState = 'active'
        useConnectivity.setState({ status: 'unknown', isConnectionExpensive: null })
        bridge.getCurrentState.mockImplementation(async () => state(true))
        bridge.eventEmitter.addListener.mockImplementation((_event, listener) => {
            nativeEvent = listener
            return { remove: jest.fn() }
        })
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
            appChange = listener
            return { remove: jest.fn() }
        })
        NetInfo.configure({ reachabilityShouldRun: () => false, useNativeReachability: false })
    })
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([false, true])(
        'a late refresh reporting %s cannot overwrite a newer native event',
        async (oldConnected) => {
            const setOnline = jest.fn()
            const stop = monitorConnectivity(setOnline)
            try {
                await jest.advanceTimersByTimeAsync(0)
                let resolve: (state: NetInfoState) => void = () => undefined
                bridge.getCurrentState.mockImplementationOnce(
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
        let resolve: (state: NetInfoState) => void = () => undefined
        bridge.getCurrentState.mockImplementationOnce(
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
