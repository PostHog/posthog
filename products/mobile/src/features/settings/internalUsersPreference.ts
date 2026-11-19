import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

interface InternalUsersPreference {
    exclude: boolean
    setExclude: (exclude: boolean) => void
}

const hydration = createPersistHydrationGate()

export const useInternalUsersPreference = create<InternalUsersPreference>()(
    persist((set) => ({ exclude: false, setExclude: (exclude) => set({ exclude }) }), {
        name: 'posthog-mobile-exclude-internal-users',
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ exclude: state.exclude }),
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

export function useInternalUsersFilter(): boolean | undefined {
    const exclude = useInternalUsersPreference((state) => state.exclude)
    const ready = useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
    return ready ? exclude : undefined
}
