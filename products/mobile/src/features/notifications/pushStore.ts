import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'
import type { PushUnavailableReason } from './pushSupport'

const hydration = createPersistHydrationGate()

/** iOS provisional authorization counts as `granted`. */
export type PushPermission = 'unknown' | 'undetermined' | 'granted' | 'denied' | 'unavailable'

/**
 * A device registration that an account which is no longer active may still hold on its host. It names the account and
 * the push token only: the removal reads that account's credentials from its own token slot when it runs.
 */
export interface OwedRemoval {
    /** The account key (`accountKey()`). */
    account: string
    /** The account's host when it left, without a trailing slash. Compared only, never used as a request target. */
    host: string
    token: string
}

export interface PushState {
    permission: PushPermission
    canAskAgain: boolean
    unavailableReason: PushUnavailableReason | null
    prompted: boolean
    /** The device's push token that the active account registered or tried to register. */
    token: string | null
    /** `host|user uuid` of the active account that `token` is registered for. Null after that account leaves. */
    registeredFor: string | null
    /** Only the active account should stay registered, so earlier accounts owe the removal of their registrations. */
    owed: OwedRemoval[]
    registering: boolean
    error: string | null
}

export const usePushStore = create<PushState>()(
    persist(
        (): PushState => ({
            permission: 'unknown',
            canAskAgain: true,
            unavailableReason: null,
            prompted: false,
            token: null,
            registeredFor: null,
            owed: [],
            registering: false,
            error: null,
        }),
        {
            name: 'posthog-mobile-push',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({
                prompted: state.prompted,
                token: state.token,
                registeredFor: state.registeredFor,
                owed: state.owed,
            }),
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

/** Resolves once the persisted `prompted` flag and token have loaded, so a cold start never asks twice. */
export function waitForPushHydration(): Promise<void> {
    return hydration.wait()
}

export function hostKey(host: string): string {
    return host.replace(/\/+$/, '').toLowerCase()
}

/** Records a removal that an account owes, once per account and token. */
export function oweRemoval(removal: OwedRemoval): void {
    usePushStore.setState((state) => ({
        owed: [
            ...state.owed.filter((owed) => owed.account !== removal.account || owed.token !== removal.token),
            removal,
        ],
    }))
}

/** Drops every owed removal that `settled` matches. */
export function settleRemovals(settled: (removal: OwedRemoval) => boolean): void {
    usePushStore.setState((state) => {
        const owed = state.owed.filter((removal) => !settled(removal))
        return owed.length === state.owed.length ? {} : { owed }
    })
}
