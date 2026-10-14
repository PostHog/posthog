import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask } from '@/auth/authStore'
import type { PinDisplay } from '@/model/views'

// How this phone arranges and shows its pins. Membership syncs with the web's starred rows; order and display mode
// stay on the device. The server's `order` is never written: `reorder` is closed to OAuth, and a PATCH would move a
// pin from a sibling environment into this one. Shortcut ids are UUIDs, so the keys need no project.

export interface PinPrefs {
    /** Dense local ranks, keyed by shortcut id. A pin without one sorts after the ranked pins. */
    rank: Record<string, number>
    /** Keyed by shortcut id. A missing entry means Row. */
    display: Record<string, PinDisplay>
}

/** Ids in their new order after moving one id up (-1) or down (1). The same order when it cannot move. */
export function movedOrder(ids: readonly string[], id: string, direction: -1 | 1): string[] {
    const index = ids.indexOf(id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= ids.length) {
        return [...ids]
    }
    const next = [...ids]
    next[index] = ids[target] as string
    next[target] = id
    return next
}

export function denseRanks(ids: readonly string[]): Record<string, number> {
    return Object.fromEntries(ids.map((id, index) => [id, index]))
}

/**
 * Drops the prefs of pins that left the server list. Only a complete list may prune: a list cut at the page size does
 * not show every pin, and pruning it would forget the order of the pins past the cut.
 */
export function prunedPrefs(prefs: PinPrefs, presentIds: readonly string[], complete: boolean): PinPrefs {
    if (!complete) {
        return prefs
    }
    const present = new Set(presentIds)
    const keep = <T>(record: Record<string, T>): Record<string, T> =>
        Object.fromEntries(Object.entries(record).filter(([id]) => present.has(id)))
    return { rank: keep(prefs.rank), display: keep(prefs.display) }
}

interface PinPrefsState extends PinPrefs {
    setDisplay: (shortcutId: string, display: PinDisplay) => void
    /** Rewrites dense ranks for the pins in the order shown. */
    setOrder: (shortcutIds: readonly string[]) => void
    prune: (presentIds: readonly string[], complete: boolean) => void
    clear: () => void
}

export const usePinPrefs = create<PinPrefsState>()(
    persist(
        (set) => ({
            rank: {},
            display: {},
            setDisplay: (shortcutId, display) =>
                set((state) => ({ display: { ...state.display, [shortcutId]: display } })),
            setOrder: (shortcutIds) => set({ rank: denseRanks(shortcutIds) }),
            prune: (presentIds, complete) =>
                set((state) => prunedPrefs({ rank: state.rank, display: state.display }, presentIds, complete)),
            clear: () => set({ rank: {}, display: {} }),
        }),
        {
            name: 'views-pin-prefs:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ rank: state.rank, display: state.display }),
        }
    )
)

addSessionEndTask(() => usePinPrefs.getState().clear())
