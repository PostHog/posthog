import Constants from 'expo-constants'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'

import { ApiError } from '@/api/client'
import { registerPushToken, unregisterPushToken } from '@/api/pushTokens'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { foregroundNotificationBehavior } from './foregroundNotifications'
import { type PushPermission, usePushStore, waitForPushHydration } from './pushStore'
import { notificationsSupported, pushUnavailableReason } from './pushSupport'

// Expo push messages without a `channelId` go to the channel with this id, so creating it here sets how server
// pushes look on Android.
export const ANDROID_CHANNEL_ID = 'default'

const UNREGISTER_TIMEOUT_MS = 4_000
const REGISTER_TIMEOUT_MS = 4_000
let closingSession: number | null = null

/** `never`: register only if already granted. `once`: ask the first time after sign in. `always`: ask while allowed. */
export type PromptPolicy = 'never' | 'once' | 'always'

/** `auto`: the first signed-in run. `settings`: the Enable button. `background`: a token change or a return to the app. */
const TRIGGERS: Record<PromptPolicy, 'auto' | 'settings' | 'background'> = {
    once: 'auto',
    always: 'settings',
    never: 'background',
}

type RegistrationFailure = 'token_unavailable' | 'network' | 'api_error' | 'unknown'

function registrationFailure(error: unknown, gotToken: boolean): RegistrationFailure {
    if (!gotToken) {
        return 'token_unavailable'
    }
    if (error instanceof ApiError) {
        return 'api_error'
    }
    return error instanceof TypeError ? 'network' : 'unknown'
}

export function configureNotifications(): void {
    if (!notificationsSupported()) {
        return
    }
    Notifications.setNotificationHandler({
        handleNotification: async (notification) => foregroundNotificationBehavior(notification),
    })
    void ensureAndroidChannel()
}

/** Android 13 shows the permission prompt only after the app has a channel. */
async function ensureAndroidChannel(): Promise<void> {
    if (Platform.OS !== 'android') {
        return
    }
    try {
        await Notifications.setNotificationChannelAsync(ANDROID_CHANNEL_ID, {
            name: 'Reports and agent updates',
            importance: Notifications.AndroidImportance.HIGH,
            lightColor: '#F54E00',
        })
    } catch {
        // Without the channel, Android falls back to its default channel.
    }
}

function toPermission(status: Notifications.NotificationPermissionsStatus): PushPermission {
    if (status.granted || status.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL) {
        return 'granted'
    }
    if (status.status === 'undetermined') {
        return 'undetermined'
    }
    return 'denied'
}

function registrationKey(): string | null {
    const { host, user } = useAuthStore.getState()
    return host && user ? `${host}|${user.uuid}` : null
}

function isCurrentRegistration(session: number, key: string): boolean {
    return sessionGeneration() === session && registrationKey() === key && closingSession !== session
}

async function withTimeout(work: (signal: AbortSignal) => Promise<void>, timeoutMs: number): Promise<void> {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        await Promise.race([
            work(controller.signal),
            new Promise<never>((_resolve, reject) => {
                timer = setTimeout(() => {
                    controller.abort()
                    reject(new Error('Push request timed out'))
                }, timeoutMs)
            }),
        ])
    } finally {
        if (timer) {
            clearTimeout(timer)
        }
    }
}

async function syncOnce(policy: PromptPolicy): Promise<void> {
    const session = sessionGeneration()
    const key = registrationKey()
    if (useAuthStore.getState().status !== 'signed_in' || !key || closingSession === session) {
        return
    }
    const unavailableReason = pushUnavailableReason()
    if (unavailableReason) {
        usePushStore.setState({ permission: 'unavailable', unavailableReason })
        return
    }
    await Promise.all([ensureAndroidChannel(), waitForPushHydration()])
    let status = await Notifications.getPermissionsAsync()
    const prompted = usePushStore.getState().prompted
    const mayPrompt = policy === 'always' || (policy === 'once' && !prompted)
    if (toPermission(status) !== 'granted' && status.canAskAgain && mayPrompt) {
        usePushStore.setState({ prompted: true })
        status = await Notifications.requestPermissionsAsync()
        track('mobile_push_permission_resolved', {
            permission: toPermission(status),
            can_ask_again: status.canAskAgain,
            trigger: TRIGGERS[policy],
        })
    }
    const permission = toPermission(status)
    if (!isCurrentRegistration(session, key)) {
        return
    }
    usePushStore.setState({ permission, canAskAgain: status.canAskAgain, unavailableReason: null })
    if (permission !== 'granted') {
        return
    }
    usePushStore.setState({ registering: true, error: null })
    let gotToken = false
    try {
        const projectId: unknown = Constants.expoConfig?.extra?.eas?.projectId
        const { data: token } = await Notifications.getExpoPushTokenAsync(
            typeof projectId === 'string' ? { projectId } : {}
        )
        gotToken = true
        if (!isCurrentRegistration(session, key)) {
            usePushStore.setState({ registering: false })
            return
        }
        const previous = usePushStore.getState()
        if (previous.token && previous.token !== token && previous.registeredFor === key) {
            // Keep the old token until its row is removed, so a failed delete can be retried.
            await withTimeout(
                (signal) => unregisterPushToken(previous.token as string, { signal }),
                UNREGISTER_TIMEOUT_MS
            )
        }
        if (!isCurrentRegistration(session, key)) {
            usePushStore.setState({ registering: false })
            return
        }
        // A POST may succeed on the server even when its response is lost. Retain the attempted token so sign out
        // can remove that row before dropping credentials.
        usePushStore.setState({ token, registeredFor: key })
        await withTimeout(
            (signal) => registerPushToken(token, Platform.OS === 'ios' ? 'ios' : 'android', { signal }),
            REGISTER_TIMEOUT_MS
        )
        if (!isCurrentRegistration(session, key)) {
            usePushStore.setState({ registering: false })
            return
        }
        usePushStore.setState({ registering: false })
        // Every launch re-registers the same token, so only a new registration counts as a success.
        if (previous.token !== token || previous.registeredFor !== key) {
            track('mobile_push_registration_finished', { ok: true, trigger: TRIGGERS[policy] })
        }
    } catch (error) {
        if (!isCurrentRegistration(session, key)) {
            usePushStore.setState({ registering: false })
            return
        }
        usePushStore.setState({ registering: false, error: toError(error).message })
        track('mobile_push_registration_finished', {
            ok: false,
            reason: registrationFailure(error, gotToken),
            trigger: TRIGGERS[policy],
        })
    }
}

let queue: Promise<void> = Promise.resolve()

function enqueue<T>(work: () => Promise<T>): Promise<T> {
    const result = queue.then(work, work)
    queue = result.then(
        () => undefined,
        () => undefined
    )
    return result
}

// Calls run one after another, so a Settings tap never races the automatic run after sign in.
export function syncPushRegistration(policy: PromptPolicy): Promise<void> {
    return enqueue(() => syncOnce(policy)).catch(() => undefined)
}

export async function refreshPushPermission(): Promise<void> {
    const unavailableReason = pushUnavailableReason()
    if (unavailableReason) {
        usePushStore.setState({ permission: 'unavailable', unavailableReason })
        return
    }
    try {
        const status = await Notifications.getPermissionsAsync()
        usePushStore.setState({ permission: toPermission(status), canAskAgain: status.canAskAgain })
    } catch {
        // Keep the last known state.
    }
}

export async function unregisterPush(): Promise<() => void> {
    const session = sessionGeneration()
    closingSession = session
    try {
        await enqueue(async () => {
            await waitForPushHydration()
            const { token, registeredFor } = usePushStore.getState()
            if (token && registeredFor === registrationKey()) {
                await withTimeout((signal) => unregisterPushToken(token, { signal }), UNREGISTER_TIMEOUT_MS)
            }
            usePushStore.setState({ token: null, registeredFor: null, registering: false, error: null })
        })
    } catch {
        closingSession = null
        throw new Error("Couldn't stop push notifications for this account. Check your connection and try again.")
    }
    return () => {
        if (closingSession === session) {
            closingSession = null
            void syncPushRegistration('never')
        }
    }
}
