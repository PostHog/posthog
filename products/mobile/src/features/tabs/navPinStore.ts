import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

// Which lists sit in the nav pill after Views. A device preference: it holds no account data, so sign-out keeps it,
// like the pin hint, and it applies to every project.

export type NavPin = 'errors' | 'replay' | 'web_analytics' | 'live'

export const NAV_PINS: readonly NavPin[] = ['errors', 'replay', 'web_analytics', 'live']

/** How a pinnable screen draws: as its navigation tab, or pushed above the tabs. */
export type NavChrome = 'tab' | 'stack'

/**
 * How many pin slots the pill draws after Views. The store keeps a list, so a larger cap needs no change to the saved
 * format. The slot was retired when Home became Live, so the cap is 0: the pin code stays, dormant, until the decision
 * to remove it. A saved list stays on the device and loads as no pins.
 */
export const MAX_NAV_PINS = 0

/** False while the slot is retired, which hides every "Pin to navigation" and "Unpin from navigation" item. */
export const NAV_PINS_ENABLED = MAX_NAV_PINS > 0

const NO_PINS: readonly NavPin[] = []

/** The last `MAX_NAV_PINS` entries. `slice(-MAX_NAV_PINS)` would keep every entry when the cap is 0. */
export function newestNavPins(pins: readonly NavPin[]): readonly NavPin[] {
    return pins.slice(Math.max(0, pins.length - MAX_NAV_PINS))
}

export function isNavPin(value: unknown): value is NavPin {
    return typeof value === 'string' && (NAV_PINS as readonly string[]).includes(value)
}

export function nextNavPins(pins: readonly NavPin[], pin: NavPin, pinned: boolean): readonly NavPin[] {
    const without = pins.filter((current) => current !== pin)
    if (!pinned) {
        return without.length === pins.length ? pins : without
    }
    if (without.length !== pins.length) {
        return pins
    }
    return newestNavPins([...without, pin])
}

/** A saved list with unknown or repeated entries, such as one from a later app version, keeps only what fits. */
export function sanitizedNavPins(value: unknown): readonly NavPin[] {
    if (!Array.isArray(value)) {
        return NO_PINS
    }
    const pins = value.filter(isNavPin).filter((pin, index, all) => all.indexOf(pin) === index)
    return pins.slice(0, MAX_NAV_PINS)
}

interface NavPinState {
    pins: readonly NavPin[]
    setPinned: (pin: NavPin, pinned: boolean) => void
}

const hydration = createPersistHydrationGate()

export const useNavPinStore = create<NavPinState>()(
    persist(
        (set) => ({
            pins: NO_PINS,
            setPinned: (pin, pinned) =>
                set((state) => {
                    const pins = nextNavPins(state.pins, pin, pinned)
                    return pins === state.pins ? state : { pins }
                }),
        }),
        {
            name: 'nav-pins:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ pins: state.pins }),
            // A pin made before the saved list loads must survive that load.
            merge: (persisted, current) => {
                const saved = sanitizedNavPins(
                    typeof persisted === 'object' && persisted !== null && 'pins' in persisted ? persisted.pins : null
                )
                const pins = current.pins.reduce((all, pin) => nextNavPins(all, pin, true), saved)
                return { ...current, pins }
            },
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

export function replacedNavPin(pins: readonly NavPin[], pin: NavPin): NavPin | null {
    if (pins.includes(pin)) {
        return null
    }
    return pins.find((current) => !nextNavPins(pins, pin, true).includes(current)) ?? null
}

export function useNavPins(): readonly NavPin[] {
    return useNavPinStore((state) => state.pins)
}

export function useIsNavPinned(pin: NavPin): boolean {
    return useNavPinStore((state) => state.pins.includes(pin))
}

export function setNavPinned(pin: NavPin, pinned: boolean): void {
    useNavPinStore.getState().setPinned(pin, pinned)
}

export function restoreNavPins(pins: readonly NavPin[]): void {
    useNavPinStore.setState({ pins: sanitizedNavPins(pins) })
}

/** True once the saved pins have loaded, so the pill does not grow a slot a moment after launch. */
export function useNavPinsHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}
