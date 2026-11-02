import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

// Which lists sit in the nav pill after Views. A device preference: it holds no account data, so sign-out keeps it,
// like the pin hint, and it applies to every project.

export type NavPin = 'errors' | 'replay'

export const NAV_PINS: readonly NavPin[] = ['errors', 'replay']

/**
 * The pill fits Home, Chats, Views and this many 44pt pin slots next to the labelled Chat button on a 375pt phone.
 * The store keeps a list, so a larger cap needs no change to the saved format.
 */
export const MAX_NAV_PINS = 1

const NO_PINS: readonly NavPin[] = []

function isNavPin(value: unknown): value is NavPin {
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
    return [...without, pin].slice(-MAX_NAV_PINS)
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
