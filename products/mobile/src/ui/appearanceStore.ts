import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { type ColorSchemeName, Appearance as NativeAppearance } from 'react-native'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'
import type { ColorScheme } from './theme'

export type Appearance = 'system' | 'light' | 'dark'

export const APPEARANCES: readonly Appearance[] = ['system', 'light', 'dark']

export function resolveColorScheme(
    appearance: Appearance,
    deviceScheme: ColorSchemeName | null | undefined
): ColorScheme {
    if (appearance !== 'system') {
        return appearance
    }
    return deviceScheme === 'dark' ? 'dark' : 'light'
}

function isAppearance(value: unknown): value is Appearance {
    return typeof value === 'string' && (APPEARANCES as readonly string[]).includes(value)
}

interface AppearanceState {
    appearance: Appearance
    setAppearance: (appearance: Appearance) => void
}

const hydration = createPersistHydrationGate()

export const useAppearanceStore = create<AppearanceState>()(
    persist((set) => ({ appearance: 'system', setAppearance: (appearance) => set({ appearance }) }), {
        name: 'posthog-mobile-appearance',
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ appearance: state.appearance }),
        // A value this build does not know falls back to the device scheme instead of an undefined palette.
        merge: (persisted, current) => {
            const appearance =
                typeof persisted === 'object' && persisted !== null && 'appearance' in persisted
                    ? persisted.appearance
                    : null
            return isAppearance(appearance) ? { ...current, appearance } : current
        },
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

export function useAppearanceHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

// Native UI (the keyboard, alerts, pickers) reads the OS scheme, so the override is pushed down to it as well.
// react-native-web has no setColorScheme; there the theme hook alone applies the override.
function applyNativeAppearance(appearance: Appearance): void {
    if (typeof NativeAppearance.setColorScheme !== 'function') {
        return
    }
    NativeAppearance.setColorScheme(appearance === 'system' ? 'unspecified' : appearance)
}

useAppearanceStore.subscribe((state, previous) => {
    if (state.appearance !== previous.appearance) {
        applyNativeAppearance(state.appearance)
    }
})
