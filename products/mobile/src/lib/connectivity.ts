import NetInfo, { type NetInfoState } from '@react-native-community/netinfo'
import { AppState } from 'react-native'
import { create } from 'zustand'

export interface Connectivity {
    status: 'unknown' | 'connected' | 'offline'
    isConnectionExpensive: boolean | null
}

export const useConnectivity = create<Connectivity>(() => ({ status: 'unknown', isConnectionExpensive: null }))

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

let configured = false

export function monitorConnectivity(setOnline: (online: boolean) => void): () => void {
    if (!configured) {
        // Connectivity is a hint, not a backend health check. Do not send NetInfo's external reachability probes.
        NetInfo.configure({ reachabilityShouldRun: () => false, useNativeReachability: false })
        configured = true
    }
    let disposed = false
    let revision = 0
    let refreshing = false
    let events: NetInfoState[] = []
    let flushTimer: ReturnType<typeof setTimeout> | undefined
    const discarded = new WeakSet<NetInfoState>()
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
                const ownEvents = events.filter((event) => event === state).length
                if (revision > started + ownEvents) discarded.add(state)
                else if (ownEvents === 0) apply(state)
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
        events.push(state)
        if (flushTimer === undefined) {
            // NetInfo publishes refresh snapshots before resolving their promise. Identify stale snapshots before delivery.
            flushTimer = setTimeout(() => {
                flushTimer = undefined
                const pending = events
                events = []
                for (const event of pending) {
                    if (!discarded.has(event)) apply(event)
                }
            }, 0)
        }
    })
    const subscription = AppState.addEventListener('change', (next) => {
        const becameActive = next === 'active' && appState !== 'active'
        appState = next
        if (becameActive) refresh()
    })
    refresh()
    return () => {
        disposed = true
        if (flushTimer !== undefined) clearTimeout(flushTimer)
        events = []
        unsubscribe()
        subscription.remove()
    }
}
