import NetInfo, { type NetInfoState } from '@react-native-community/netinfo'
import { AppState } from 'react-native'
import { create } from 'zustand'

export interface Connectivity {
    status: 'unknown' | 'connected' | 'offline'
    isConnectionExpensive: boolean | null
}

export const useConnectivity = create<Connectivity>(() => ({ status: 'unknown', isConnectionExpensive: null }))

let configured = false

export function monitorConnectivity(setOnline: (online: boolean) => void): () => void {
    if (!configured) {
        // Connectivity is a hint, not a backend health check. Do not send NetInfo's external reachability probes.
        NetInfo.configure({ reachabilityShouldRun: () => false })
        configured = true
    }
    let disposed = false
    let revision = 0
    let refreshing = false
    let appState = AppState.currentState
    const apply = (state: NetInfoState): void => {
        if (disposed) return
        // With probes disabled, NetInfo can report unreachable for an unsupported platform. Use the device link only.
        const status = state.isConnected === false ? 'offline' : state.isConnected === true ? 'connected' : 'unknown'
        const isConnectionExpensive = state.details?.isConnectionExpensive ?? null
        const previous = useConnectivity.getState()
        if (status !== previous.status || isConnectionExpensive !== previous.isConnectionExpensive) {
            useConnectivity.setState({ status, isConnectionExpensive })
        }
        setOnline(status !== 'offline')
    }
    const refresh = (): void => {
        if (refreshing || disposed) return
        refreshing = true
        const started = revision
        void NetInfo.refresh()
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
    const unsubscribe = NetInfo.addEventListener((state) => {
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
        unsubscribe()
        subscription.remove()
    }
}
