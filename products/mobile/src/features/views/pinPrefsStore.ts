import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { legacyEntriesFor } from '@/auth/accountKey'
import { addAccountRemovedTask, launchAccount } from '@/auth/authStore'
import { waitForPersist } from '@/lib/persistHydration'
import type { PinDisplay } from '@/model/views'

// How this phone arranges and shows its pins. Membership syncs with the web's starred rows; order and display mode
// stay on the device. The server's `order` is never written: `reorder` is closed to OAuth, and a PATCH would move a
// pin from a sibling environment into this one. Prefs are kept per account and project, because a complete pin list
// read prunes the ids it does not hold, and the list holds one account's pins in one project only.

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

type ProjectPinPrefs = Record<string, PinPrefs>

interface PinPrefsState {
    /** Keyed by account key, then by `{host}|{project id}`. */
    accounts: Record<string, ProjectPinPrefs>
    /** Prefs that an app version before multi-account stored, until `adoptLegacy` gives them to their account. */
    legacy: ProjectPinPrefs | null
    setDisplay: (account: string, projectKey: string, shortcutId: string, display: PinDisplay) => void
    /** Rewrites dense ranks for the pins in the order shown. */
    setOrder: (account: string, projectKey: string, shortcutIds: readonly string[]) => void
    prune: (account: string, projectKey: string, presentIds: readonly string[], complete: boolean) => void
    removeAccount: (account: string) => void
}

function withProject(
    state: PinPrefsState,
    account: string,
    projectKey: string,
    change: (prefs: PinPrefs) => PinPrefs
): Pick<PinPrefsState, 'accounts'> | PinPrefsState {
    const projects = state.accounts[account] ?? {}
    const prefs = projects[projectKey] ?? NO_PIN_PREFS
    const next = change(prefs)
    return next === prefs ? state : { accounts: { ...state.accounts, [account]: { ...projects, [projectKey]: next } } }
}

export const usePinPrefs = create<PinPrefsState>()(
    persist<PinPrefsState, [], [], Pick<PinPrefsState, 'accounts' | 'legacy'>>(
        (set, get) => ({
            accounts: {},
            legacy: null,
            setDisplay: (account, projectKey, shortcutId, display) =>
                set((state) =>
                    withProject(state, account, projectKey, (prefs) => ({
                        ...prefs,
                        display: { ...prefs.display, [shortcutId]: display },
                    }))
                ),
            setOrder: (account, projectKey, shortcutIds) =>
                set((state) =>
                    withProject(state, account, projectKey, (prefs) => ({ ...prefs, rank: denseRanks(shortcutIds) }))
                ),
            prune: (account, projectKey, presentIds, complete) => {
                // A read that removes nothing must not call `set`: `persist` writes AsyncStorage on every `set`.
                const prefs = get().accounts[account]?.[projectKey]
                if (prefs && prunedPrefs(prefs, presentIds, complete) !== prefs) {
                    set((state) =>
                        withProject(state, account, projectKey, (current) => prunedPrefs(current, presentIds, complete))
                    )
                }
            },
            removeAccount: (account) => {
                if (account in get().accounts) {
                    set((state) => {
                        const { [account]: _removed, ...rest } = state.accounts
                        return { accounts: rest }
                    })
                }
            },
        }),
        {
            name: 'views-pin-prefs:v2',
            version: 1,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ accounts: state.accounts, legacy: state.legacy }),
            // Version 0 kept one map for whoever was signed in.
            migrate: (persisted, version) => {
                const projects = (persisted as { projects?: ProjectPinPrefs } | null)?.projects
                return { accounts: {}, legacy: version === 0 && projects ? projects : null }
            },
        }
    )
)

/** One project's prefs in `account`. Null, such as in demo mode, reads none. */
export function useProjectPinPrefs(account: string | null, projectKey: string | null): PinPrefs {
    return usePinPrefs(
        (state) => (account && projectKey ? state.accounts[account]?.[projectKey] : undefined) ?? NO_PIN_PREFS
    )
}

export function accountPinPrefs(account: string | null, projectKey: string): PinPrefs {
    return (account ? usePinPrefs.getState().accounts[account]?.[projectKey] : undefined) ?? NO_PIN_PREFS
}

addAccountRemovedTask((account) => usePinPrefs.getState().removeAccount(account.key))

void Promise.all([launchAccount(), waitForPersist(usePinPrefs)]).then(([account]) => {
    const { legacy } = usePinPrefs.getState()
    if (!legacy) {
        return
    }
    const { owned } = legacyEntriesFor(legacy, account)
    usePinPrefs.setState((state) => ({
        legacy: null,
        accounts:
            account && Object.keys(owned).length > 0
                ? { ...state.accounts, [account.key]: { ...owned, ...state.accounts[account.key] } }
                : state.accounts,
    }))
})
