import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { ExternalHandoffTarget } from './externalHandoff'

export type HandoffTarget = 'posthog' | ExternalHandoffTarget

interface HandoffPreferenceState {
    target: HandoffTarget
    setTarget: (target: HandoffTarget) => void
}

export const useHandoffPreferenceStore = create<HandoffPreferenceState>()(
    persist((set) => ({ target: 'posthog', setTarget: (target) => set({ target }) }), {
        name: 'posthog-mobile-handoff-preference',
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ target: state.target }),
    })
)
