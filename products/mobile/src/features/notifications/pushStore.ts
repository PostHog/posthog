import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'
import type { PushUnavailableReason } from './pushSupport'

const hydration = createPersistHydrationGate()

/** iOS provisional authorization counts as `granted`. */
export type PushPermission = 'unknown' | 'undetermined' | 'granted' | 'denied' | 'unavailable'

export interface PushState {
    permission: PushPermission
    canAskAgain: boolean
    unavailableReason: PushUnavailableReason | null
    prompted: boolean
    token: string | null
    /** `host|user uuid` the token is registered for. */
    registeredFor: string | null
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
            }),
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

/** Resolves once the persisted `prompted` flag and token have loaded, so a cold start never asks twice. */
export function waitForPushHydration(): Promise<void> {
    return hydration.wait()
}
