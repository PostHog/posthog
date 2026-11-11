import * as Notifications from 'expo-notifications'
import { useEffect } from 'react'
import { AppState } from 'react-native'

import { addSignOutTask, useAuthStore } from '@/auth/authStore'

import { refreshPushPermission, syncPushRegistration, unregisterPush } from './pushRegistration'
import { usePushStore } from './pushStore'
import { pushUnavailableReason } from './pushSupport'

// Later launches re-register silently so the server's `last_seen_at` stays fresh.
export function usePushRegistration(): void {
    const status = useAuthStore((state) => state.status)
    const userUuid = useAuthStore((state) => state.user?.uuid ?? null)
    const host = useAuthStore((state) => state.host)
    const signedIn = status === 'signed_in' && userUuid !== null

    useEffect(() => addSignOutTask(unregisterPush), [])

    // biome-ignore lint/correctness/useExhaustiveDependencies: a new user or host needs its own registration.
    useEffect(() => {
        if (signedIn) {
            void syncPushRegistration('once')
        }
    }, [signedIn, userUuid, host])

    useEffect(() => {
        if (!signedIn || pushUnavailableReason()) {
            return
        }
        const tokenSubscription = Notifications.addPushTokenListener(() => {
            void syncPushRegistration('never')
        })
        // The user can turn notifications on in system settings while the app is in the background.
        const appStateSubscription = AppState.addEventListener('change', (next) => {
            if (next !== 'active') {
                return
            }
            void refreshPushPermission().then(() => {
                const push = usePushStore.getState()
                if (
                    push.permission === 'granted' &&
                    (!push.token || push.error || push.registeredFor !== `${host}|${userUuid}`)
                ) {
                    void syncPushRegistration('never')
                }
            })
        })
        return () => {
            tokenSubscription.remove()
            appStateSubscription.remove()
        }
    }, [signedIn, host, userUuid])
}
