import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask } from '@/auth/authStore'

// Each person on this device agrees once that PostHog AI sends chat data to third-party model providers.
// The key carries the host, because the same person on another instance has a separate account.

export function aiConsentKey(host: string, userUuid: string): string {
    return `${host}|${userUuid}`
}

interface AiConsentState {
    /** Keyed by `aiConsentKey`. */
    accepted: Record<string, true>
    accept: (key: string) => void
    clear: () => void
}

export const useAiConsentStore = create<AiConsentState>()(
    persist(
        (set) => ({
            accepted: {},
            accept: (key) =>
                set((state) => (state.accepted[key] ? state : { accepted: { ...state.accepted, [key]: true } })),
            clear: () => set({ accepted: {} }),
        }),
        {
            name: 'posthog-mobile-ai-consent',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ accepted: state.accepted }),
        }
    )
)

/** True once the stored consent has loaded, so a person who already agreed never sees the sheet flash. */
export function useAiConsentHydrated(): boolean {
    const [hydrated, setHydrated] = useState(() => useAiConsentStore.persist.hasHydrated())
    useEffect(() => {
        const unsubscribe = useAiConsentStore.persist.onFinishHydration(() => setHydrated(true))
        setHydrated(useAiConsentStore.persist.hasHydrated())
        return unsubscribe
    }, [])
    return hydrated
}

// Consent is per-user state like the rest, so sign out and session expiry drop it, and the next sign-in asks again.
addSessionEndTask(() => useAiConsentStore.getState().clear())
