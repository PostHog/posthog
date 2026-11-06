import { addNetworkStateListener, getNetworkStateAsync, type NetworkState, NetworkStateType } from 'expo-network'
import { AppState } from 'react-native'
import { create } from 'zustand'

export interface Connectivity {
    status: 'unknown' | 'connected' | 'offline'
    type: NetworkStateType
}

export const useConnectivity = create<Connectivity>(() => ({ status: 'unknown', type: NetworkStateType.UNKNOWN }))

export class OfflineError extends Error {
    constructor() {
        super("You're offline. Reconnect and try again.")
        this.name = 'OfflineError'
    }
}

// Stop an action waiting on a read when the link drops, without canceling a query another screen may share.
export async function whileOnline<T>(read: () => Promise<T>): Promise<T> {
    if (useConnectivity.getState().status === 'offline') throw new OfflineError()
    let unsubscribe = (): void => undefined
    const disconnected = new Promise<never>((_resolve, reject) => {
        unsubscribe = useConnectivity.subscribe((state) => {
            if (state.status === 'offline') reject(new OfflineError())
        })
    })
    try {
        return await Promise.race([read(), disconnected])
    } finally {
        unsubscribe()
    }
}

export function monitorConnectivity(setOnline: (online: boolean) => void): () => void {
    let disposed = false
    let revision = 0
    let refreshing = false
    let appState = AppState.currentState
    const apply = (state: NetworkState): void => {
        if (disposed) return
        // Expo can report UNKNOWN with isConnected=false when the native state cannot be read. Allow requests then.
        // Reachability is not a backend health check, so only a known disconnected link pauses reads.
        const status =
            state.isConnected === true
                ? 'connected'
                : state.isConnected === false && state.type !== NetworkStateType.UNKNOWN
                  ? 'offline'
                  : 'unknown'
        const type = state.type ?? NetworkStateType.UNKNOWN
        if (status !== useConnectivity.getState().status || type !== useConnectivity.getState().type)
            useConnectivity.setState({ status, type })
        setOnline(status !== 'offline')
    }
    const refresh = (): void => {
        if (refreshing || disposed) return
        refreshing = true
        const started = revision
        void getNetworkStateAsync()
            .then((state) => {
                if (revision === started) apply(state)
            })
            .catch(() => {
                // A failed native read does not prove the device is offline. Keep the last observed state.
            })
            .finally(() => {
                refreshing = false
            })
    }
    const networkSubscription = addNetworkStateListener((state) => {
        revision += 1
        apply(state)
    })
    const subscription = AppState.addEventListener('change', (next) => {
        const becameActive = next === 'active' && appState !== 'active'
        appState = next
        if (becameActive) refresh()
    })
    refresh()
    return () => {
        disposed = true
        networkSubscription.remove()
        subscription.remove()
    }
}
