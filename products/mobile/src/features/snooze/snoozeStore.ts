import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { type AccountRef, legacyEntriesFor } from '@/auth/accountKey'

import { pruneSnoozes, type SnoozeEntry } from './snoozeEntries'

export const NO_SNOOZES: Record<string, SnoozeEntry> = {}

/** A delivered reminder can stay in the notification list long after its snooze ends, so its owner stays this long. */
const REMINDER_OWNER_MS = 30 * 24 * 60 * 60 * 1000

/** The account that scheduled a reminder. `account` is null after that account left the device. */
export interface ReminderOwner {
    account: string | null
    until: string
}

export interface SnoozeState {
    /** Keyed by account key, then by `snoozeKey(scope, reportId)`. Two accounts on one project never share a snooze. */
    accounts: Record<string, Record<string, SnoozeEntry>>
    /** Snoozes that an app version before multi-account stored, until `adoptLegacy` gives them to their account. */
    legacy: Record<string, SnoozeEntry> | null
    /**
     * Keyed by the reminder's notification identifier. A tap reads it there, because the Android tap store keeps only
     * the routing fields of a notification's data, and the snooze entry is pruned once its time passes.
     */
    reminderOwners: Record<string, ReminderOwner>
    put: (account: string, key: string, entry: SnoozeEntry) => void
    take: (account: string, key: string) => SnoozeEntry | undefined
    prune: (now: Date) => void
    /** Removes one account's snoozes and returns what it removed. Its reminders keep an owner that names no account. */
    removeAccount: (account: string) => SnoozeEntry[]
    /** Gives the legacy snoozes on `account`'s host to it and returns the ones it dropped. */
    adoptLegacy: (account: AccountRef | null) => SnoozeEntry[]
}

export const useSnoozeStore = create<SnoozeState>()(
    persist(
        (set, get) => ({
            accounts: {},
            legacy: null,
            reminderOwners: {},
            put: (account, key, entry) =>
                set((state) => ({
                    accounts: {
                        ...state.accounts,
                        [account]: { ...pruneSnoozes(state.accounts[account] ?? {}, new Date()), [key]: entry },
                    },
                    ...(entry.kind === 'until' && entry.notificationId
                        ? {
                              reminderOwners: {
                                  ...state.reminderOwners,
                                  [entry.notificationId]: { account, until: entry.until },
                              },
                          }
                        : {}),
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
                    reminderOwners: Object.fromEntries(
                        Object.entries(state.reminderOwners).filter(
                            ([, owner]) => new Date(owner.until).getTime() + REMINDER_OWNER_MS > now.getTime()
                        )
                    ),
                })),
            removeAccount: (account) => {
                const removed = Object.values(get().accounts[account] ?? {})
                set((state) => {
                    const { [account]: _removed, ...rest } = state.accounts
                    return {
                        accounts: rest,
                        // A delivered reminder of this account can still be tapped, and that tap must not open in
                        // another account. The owner keeps no account key, so nothing names the account any more.
                        reminderOwners: Object.fromEntries(
                            Object.entries(state.reminderOwners).map(([id, owner]) => [
                                id,
                                owner.account === account ? { ...owner, account: null } : owner,
                            ])
                        ),
                    }
                })
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
            partialize: (state) => ({
                accounts: state.accounts,
                legacy: state.legacy,
                reminderOwners: state.reminderOwners,
            }),
            // Version 0 kept one map for whoever was signed in.
            migrate: (persisted, version) => {
                const entries = (persisted as { entries?: Record<string, SnoozeEntry> } | null)?.entries
                return { accounts: {}, legacy: version === 0 && entries ? entries : null } as unknown as SnoozeState
            },
            onRehydrateStorage: () => (state) => state?.prune(new Date()),
        }
    )
)
