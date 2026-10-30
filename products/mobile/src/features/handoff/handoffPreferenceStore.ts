import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { POSTHOG_AGENT } from '@/model/agent'

import type { ExternalHandoffTarget } from './externalHandoff'

export type HandoffTarget = 'posthog' | ExternalHandoffTarget

export function handoffAgentName(target: HandoffTarget): string {
    return target === 'posthog' ? POSTHOG_AGENT.name : target === 'claude' ? 'Claude Code' : 'Codex'
}

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
