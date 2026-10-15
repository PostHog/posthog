import Constants from 'expo-constants'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'

import { registerPushToken, unregisterPushToken } from '@/api/pushTokens'
import { useAuthStore } from '@/auth/authStore'
import { toError } from '@/lib/errors'
import { foregroundNotificationBehavior } from './foregroundNotifications'
import { type PushPermission, usePushStore, waitForPushHydration } from './pushStore'
import { notificationsSupported, pushUnavailableReason } from './pushSupport'

// Expo push messages without a `channelId` go to the channel with this id, so creating it here sets how server
// pushes look on Android.
export const ANDROID_CHANNEL_ID = 'default'

const UNREGISTER_TIMEOUT_MS = 4_000

/** `never`: register only if already granted. `once`: ask the first time after sign in. `always`: ask while allowed. */
export type PromptPolicy = 'never' | 'once' | 'always'

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

async function syncOnce(policy: PromptPolicy): Promise<void> {
    const key = registrationKey()
    if (useAuthStore.getState().status !== 'signed_in' || !key) {
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
    }
    const permission = toPermission(status)
    usePushStore.setState({ permission, canAskAgain: status.canAskAgain, unavailableReason: null })
    if (permission !== 'granted') {
        return
    }
    usePushStore.setState({ registering: true, error: null })
    try {
        const projectId: unknown = Constants.expoConfig?.extra?.eas?.projectId
        const { data: token } = await Notifications.getExpoPushTokenAsync(
            typeof projectId === 'string' ? { projectId } : {}
        )
        const previous = usePushStore.getState()
        await registerPushToken(token, Platform.OS === 'ios' ? 'ios' : 'android')
        if (previous.token && previous.token !== token && previous.registeredFor === key) {
            // The OS issued a new token. The old row would only collect undeliverable pushes.
            unregisterPushToken(previous.token).catch(() => undefined)
        }
        usePushStore.setState({ token, registeredFor: key, registering: false })
    } catch (error) {
        usePushStore.setState({ registering: false, error: toError(error).message })
    }
}

let queue: Promise<void> = Promise.resolve()

// Calls run one after another, so a Settings tap never races the automatic run after sign in.
export function syncPushRegistration(policy: PromptPolicy): Promise<void> {
    queue = queue.then(() => syncOnce(policy)).catch(() => undefined)
    return queue
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

// When this fails (offline, or the token was already dead), the server keeps the row and the device keeps getting
// that user's pushes. Nothing can remove it later, because the app no longer has a token for that user.
// docs/GAPS.md lists this.
export async function unregisterPush(): Promise<void> {
    const { token } = usePushStore.getState()
    if (!token) {
        return
    }
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), UNREGISTER_TIMEOUT_MS)
    try {
        await unregisterPushToken(token, { signal: controller.signal })
    } catch {
        // Sign out continues; see the comment above.
    } finally {
        clearTimeout(timer)
    }
    usePushStore.setState({ token: null, registeredFor: null, error: null })
}
