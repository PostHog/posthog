import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask } from '@/auth/authStore'
import type { DeviceRecentEntry } from '@/model/views'

/** Views opened on this phone, kept per project. Phone opens never reach the web's view log, so the device keeps them. */
export const DEVICE_RECENT_LIMIT = 20

export function withRecent(
    entries: readonly DeviceRecentEntry[],
    entry: DeviceRecentEntry,
    limit = DEVICE_RECENT_LIMIT
): DeviceRecentEntry[] {
    const rest = entries.filter((existing) => existing.kind !== entry.kind || existing.ref !== entry.ref)
    return [entry, ...rest].slice(0, limit)
}

interface RecentState {
    /** Keyed by `{host}|{project id}`. */
    entries: Record<string, DeviceRecentEntry[]>
    record: (projectKey: string, entry: DeviceRecentEntry) => void
    clear: () => void
}

export const useDeviceRecent = create<RecentState>()(
    persist(
        (set) => ({
            entries: {},
            record: (projectKey, entry) =>
                set((state) => ({
                    entries: { ...state.entries, [projectKey]: withRecent(state.entries[projectKey] ?? [], entry) },
                })),
            clear: () => set({ entries: {} }),
        }),
        {
            name: 'views-recent:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ entries: state.entries }),
        }
    )
)

addSessionEndTask(() => useDeviceRecent.getState().clear())
