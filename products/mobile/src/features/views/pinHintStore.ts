import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

// Sign-out does not clear this flag, unlike the pin prefs: it holds no account data, and a person who signs in again
// on this phone already knows the gesture.

interface PinHintState {
    dismissed: boolean
    dismiss: () => void
}

const hydration = createPersistHydrationGate()

export const usePinHintStore = create<PinHintState>()(
    persist((set) => ({ dismissed: false, dismiss: () => set({ dismissed: true }) }), {
        name: 'views-pin-hint:v1',
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ dismissed: state.dismissed }),
        // A dismissal made before the saved value loads must survive that load.
        merge: (persisted, current) => {
            const saved =
                typeof persisted === 'object' && persisted !== null && 'dismissed' in persisted
                    ? persisted.dismissed === true
                    : false
            return { ...current, dismissed: current.dismissed || saved }
        },
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

/** True once the saved flag has loaded, so the hint does not flash for a person who already dismissed it. */
export function usePinHintHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}
