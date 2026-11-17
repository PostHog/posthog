import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { type AccountRef, legacyEntriesFor } from '@/auth/accountKey'

import { pruneSnoozes, type SnoozeEntry } from './snoozeEntries'

export const NO_SNOOZES: Record<string, SnoozeEntry> = {}

export interface SnoozeState {
    /** Keyed by account key, then by `snoozeKey(scope, reportId)`. Two accounts on one project never share a snooze. */
    accounts: Record<string, Record<string, SnoozeEntry>>
    /** Snoozes that an app version before multi-account stored, until `adoptLegacy` gives them to their account. */
    legacy: Record<string, SnoozeEntry> | null
    put: (account: string, key: string, entry: SnoozeEntry) => void
    take: (account: string, key: string) => SnoozeEntry | undefined
    prune: (now: Date) => void
    /** Removes one account's snoozes and returns what it removed. */
    removeAccount: (account: string) => SnoozeEntry[]
    /** Gives the legacy snoozes on `account`'s host to it and returns the ones it dropped. */
    adoptLegacy: (account: AccountRef | null) => SnoozeEntry[]
}

export const useSnoozeStore = create<SnoozeState>()(
    persist(
        (set, get) => ({
            accounts: {},
            legacy: null,
            put: (account, key, entry) =>
                set((state) => ({
                    accounts: {
                        ...state.accounts,
                        [account]: { ...pruneSnoozes(state.accounts[account] ?? {}, new Date()), [key]: entry },
                    },
                })),
            take: (account, key) => {
                const entry = get().accounts[account]?.[key]
                if (entry) {
                    set((state) => {
                        const { [key]: _removed, ...rest } = state.accounts[account] ?? {}
                        return { accounts: { ...state.accounts, [account]: rest } }
                    })
                }
                return entry
            },
            prune: (now) =>
                set((state) => ({
                    accounts: Object.fromEntries(
                        Object.entries(state.accounts).map(([account, entries]) => [
                            account,
                            pruneSnoozes(entries, now),
                        ])
                    ),
                })),
            removeAccount: (account) => {
                const removed = Object.values(get().accounts[account] ?? {})
                if (account in get().accounts) {
                    set((state) => {
                        const { [account]: _removed, ...rest } = state.accounts
                        return { accounts: rest }
                    })
                }
                return removed
            },
            adoptLegacy: (account) => {
                const { legacy } = get()
                if (!legacy) {
                    return []
                }
                const { owned, dropped } = legacyEntriesFor(legacy, account)
                set((state) => ({
                    legacy: null,
                    accounts:
                        account && Object.keys(owned).length > 0
                            ? { ...state.accounts, [account.key]: { ...owned, ...state.accounts[account.key] } }
                            : state.accounts,
                }))
                return dropped
            },
        }),
        {
            name: 'posthog-mobile-snoozes',
            version: 1,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ accounts: state.accounts, legacy: state.legacy }),
            // Version 0 kept one map for whoever was signed in.
            migrate: (persisted, version) => {
                const entries = (persisted as { entries?: Record<string, SnoozeEntry> } | null)?.entries
                return { accounts: {}, legacy: version === 0 && entries ? entries : null } as unknown as SnoozeState
            },
            onRehydrateStorage: () => (state) => state?.prune(new Date()),
        }
    )
)
