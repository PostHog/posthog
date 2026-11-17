import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { legacyEntriesFor } from '@/auth/accountKey'
import { addAccountRemovedTask, launchAccount } from '@/auth/authStore'
import { waitForPersist } from '@/lib/persistHydration'
import type { DeviceRecentEntry } from '@/model/views'

/**
 * Views opened on this phone, kept per account and project. Phone opens never reach the web's view log, so the device
 * keeps them.
 */
export const DEVICE_RECENT_LIMIT = 20

export function withRecent(
    entries: readonly DeviceRecentEntry[],
    entry: DeviceRecentEntry,
    limit = DEVICE_RECENT_LIMIT
): DeviceRecentEntry[] {
    const rest = entries.filter((existing) => existing.kind !== entry.kind || existing.ref !== entry.ref)
    return [entry, ...rest].slice(0, limit)
}

type ProjectRecents = Record<string, DeviceRecentEntry[]>

interface RecentState {
    /** Keyed by account key, then by `{host}|{project id}`. */
    accounts: Record<string, ProjectRecents>
    /** Entries that an app version before multi-account stored, until launch gives them to their account. */
    legacy: ProjectRecents | null
    record: (account: string, projectKey: string, entry: DeviceRecentEntry) => void
    removeAccount: (account: string) => void
}

export const useDeviceRecent = create<RecentState>()(
    persist<RecentState, [], [], Pick<RecentState, 'accounts' | 'legacy'>>(
        (set, get) => ({
            accounts: {},
            legacy: null,
            record: (account, projectKey, entry) =>
                set((state) => {
                    const projects = state.accounts[account] ?? {}
                    return {
                        accounts: {
                            ...state.accounts,
                            [account]: { ...projects, [projectKey]: withRecent(projects[projectKey] ?? [], entry) },
                        },
                    }
                }),
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
            name: 'views-recent:v1',
            version: 1,
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ accounts: state.accounts, legacy: state.legacy }),
            // Version 0 kept one map for whoever was signed in.
            migrate: (persisted, version) => {
                const entries = (persisted as { entries?: ProjectRecents } | null)?.entries
                return { accounts: {}, legacy: version === 0 && entries ? entries : null }
            },
        }
    )
)

addAccountRemovedTask((account) => useDeviceRecent.getState().removeAccount(account.key))

void Promise.all([launchAccount(), waitForPersist(useDeviceRecent)]).then(([account]) => {
    const { legacy } = useDeviceRecent.getState()
    if (!legacy) {
        return
    }
    const { owned } = legacyEntriesFor(legacy, account)
    useDeviceRecent.setState((state) => ({
        legacy: null,
        accounts:
            account && Object.keys(owned).length > 0
                ? { ...state.accounts, [account.key]: { ...owned, ...state.accounts[account.key] } }
                : state.accounts,
    }))
})
