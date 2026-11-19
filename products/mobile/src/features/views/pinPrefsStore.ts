import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { addSessionEndTask } from '@/auth/authStore'
import type { PinDisplay } from '@/model/views'

// How this phone arranges and shows its pins. Membership syncs with the web's starred rows; order and display mode
// stay on the device. The server's `order` is never written: `reorder` is closed to OAuth, and a PATCH would move a
// pin from a sibling environment into this one. Prefs are kept per project, because a complete pin list read prunes
// the ids it does not hold, and the list holds one project's pins only.

export interface PinPrefs {
    /** Dense local ranks, keyed by shortcut id. A pin without one sorts after the ranked pins. */
    rank: Record<string, number>
    /** Keyed by shortcut id. A missing entry allows an automatic display on the Views list. */
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

export const NO_PIN_PREFS: PinPrefs = { rank: {}, display: {} }

/**
 * Drops the prefs of pins that left the server list. Only a complete list may prune: a list cut at the page size does
 * not show every pin, and pruning it would forget the order of the pins past the cut. Returns `prefs` itself when
 * nothing left, so a list read writes nothing and the pins keep their identity.
 */
export function prunedPrefs(prefs: PinPrefs, presentIds: readonly string[], complete: boolean): PinPrefs {
    if (!complete) {
        return prefs
    }
    const present = new Set(presentIds)
    const gone = (record: Record<string, unknown>): boolean => Object.keys(record).some((id) => !present.has(id))
    if (!gone(prefs.rank) && !gone(prefs.display)) {
        return prefs
    }
    const keep = <T>(record: Record<string, T>): Record<string, T> =>
        Object.fromEntries(Object.entries(record).filter(([id]) => present.has(id)))
    return { rank: keep(prefs.rank), display: keep(prefs.display) }
}

interface PinPrefsState {
    /** Keyed by `{host}|{project id}`. */
    projects: Record<string, PinPrefs>
    setDisplay: (projectKey: string, shortcutId: string, display: PinDisplay) => void
    /** Rewrites dense ranks for the pins in the order shown. */
    setOrder: (projectKey: string, shortcutIds: readonly string[]) => void
    prune: (projectKey: string, presentIds: readonly string[], complete: boolean) => void
    clear: () => void
}

function withProject(
    state: PinPrefsState,
    projectKey: string,
    change: (prefs: PinPrefs) => PinPrefs
): Pick<PinPrefsState, 'projects'> | PinPrefsState {
    const prefs = state.projects[projectKey] ?? NO_PIN_PREFS
    const next = change(prefs)
    return next === prefs ? state : { projects: { ...state.projects, [projectKey]: next } }
}

export const usePinPrefs = create<PinPrefsState>()(
    persist(
        (set, get) => ({
            projects: {},
            setDisplay: (projectKey, shortcutId, display) =>
                set((state) =>
                    withProject(state, projectKey, (prefs) => ({
                        ...prefs,
                        display: { ...prefs.display, [shortcutId]: display },
                    }))
                ),
            setOrder: (projectKey, shortcutIds) =>
                set((state) =>
                    withProject(state, projectKey, (prefs) => ({ ...prefs, rank: denseRanks(shortcutIds) }))
                ),
            prune: (projectKey, presentIds, complete) => {
                // A read that removes nothing must not call `set`: `persist` writes AsyncStorage on every `set`.
                const prefs = get().projects[projectKey]
                if (prefs && prunedPrefs(prefs, presentIds, complete) !== prefs) {
                    set((state) =>
                        withProject(state, projectKey, (current) => prunedPrefs(current, presentIds, complete))
                    )
                }
            },
            clear: () => set({ projects: {} }),
        }),
        {
            name: 'views-pin-prefs:v2',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ projects: state.projects }),
        }
    )
)

/** One project's prefs. Null, such as in demo mode, reads none. */
export function useProjectPinPrefs(projectKey: string | null): PinPrefs {
    return usePinPrefs((state) => (projectKey ? state.projects[projectKey] : undefined) ?? NO_PIN_PREFS)
}

addSessionEndTask(() => usePinPrefs.getState().clear())
