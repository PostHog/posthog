import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { pruneSnoozes, type SnoozeEntry } from './snoozeEntries'

export interface SnoozeState {
    /** Keyed by `snoozeKey(scope, reportId)`. */
    entries: Record<string, SnoozeEntry>
    put: (key: string, entry: SnoozeEntry) => void
    take: (key: string) => SnoozeEntry | undefined
    prune: (now: Date) => void
    /** Removes every entry and returns what it removed. */
    clear: () => SnoozeEntry[]
}

export const useSnoozeStore = create<SnoozeState>()(
    persist(
        (set, get) => ({
            entries: {},
            put: (key, entry) =>
                set((state) => ({ entries: { ...pruneSnoozes(state.entries, new Date()), [key]: entry } })),
            take: (key) => {
                const entry = get().entries[key]
                if (entry) {
                    set((state) => {
                        const { [key]: _removed, ...rest } = state.entries
                        return { entries: rest }
                    })
                }
                return entry
            },
            prune: (now) => set((state) => ({ entries: pruneSnoozes(state.entries, now) })),
            clear: () => {
                const removed = Object.values(get().entries)
                set({ entries: {} })
                return removed
            },
        }),
        {
            name: 'posthog-mobile-snoozes',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ entries: state.entries }),
            onRehydrateStorage: () => (state) => state?.prune(new Date()),
        }
    )
)
