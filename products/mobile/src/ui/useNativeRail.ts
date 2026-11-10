import { type EventSubscription, requireOptionalNativeModule } from 'expo'
import type { VerticalBarEdgeIOS } from 'expo-status-bar'
import { useSyncExternalStore } from 'react'
import { Platform } from 'react-native'

const statusBar = requireOptionalNativeModule<{
    addListener: (
        event: 'onVerticalBarEdgeChange',
        listener: (event: { edge: VerticalBarEdgeIOS | null }) => void
    ) => EventSubscription
}>('ExpoStatusBar')
const listeners = new Set<() => void>()
let subscription: EventSubscription | null = null
let nativeRail = false

function subscribe(listener: () => void): () => void {
    if (Platform.OS !== 'ios' || !statusBar) return () => undefined
    listeners.add(listener)
    if (!subscription) {
        // Expo sends the initial edge asynchronously; its synchronous getter can deadlock React's event beat.
        subscription = statusBar.addListener('onVerticalBarEdgeChange', ({ edge }) => {
            const next = edge === 'leading' || edge === 'trailing'
            if (next === nativeRail) return
            nativeRail = next
            for (const notify of listeners) notify()
        })
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            subscription?.remove()
            subscription = null
            nativeRail = false
        }
    }
}

function snapshot(): boolean {
    return nativeRail
}

export function useNativeRail(): boolean {
    return useSyncExternalStore(subscribe, snapshot, snapshot)
}
