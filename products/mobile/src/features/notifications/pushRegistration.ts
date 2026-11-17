import Constants from 'expo-constants'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'

import { ApiError } from '@/api/client'
import {
    type AccountCredentials,
    registerPushToken,
    unregisterPushToken,
    unregisterPushTokenFor,
} from '@/api/pushTokens'
import { TransportError } from '@/api/transport'
import { type AccountRef, useAuthStore } from '@/auth/authStore'
import { getSessionAccountKey, getSessionIdentity, readAccountSession, sessionGeneration } from '@/auth/tokens'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { foregroundNotificationBehavior } from './foregroundNotifications'
import {
    hostKey,
    type OwedRemoval,
    oweRemoval,
    type PushPermission,
    settleRemovals,
    usePushStore,
    waitForPushHydration,
} from './pushStore'
import { notificationsSupported, pushUnavailableReason } from './pushSupport'

// Expo push messages without a `channelId` go to the channel with this id, so creating it here sets how server
// pushes look on Android.
export const ANDROID_CHANNEL_ID = 'default'

const UNREGISTER_TIMEOUT_MS = 4_000
const REGISTER_TIMEOUT_MS = 4_000
const TOKEN_TIMEOUT_MS = 15_000
/** The longest an account switch or the removal of another account waits for push cleanup before it continues. */
const CLEANUP_WAIT_MS = 2_500
/** A stored access token this close to its expiry is not sent, because the host would refuse it. */
const CREDENTIALS_MARGIN_MS = 60_000
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
    return error instanceof TransportError ? 'network' : 'unknown'
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

async function withTimeout<T>(work: (signal: AbortSignal) => Promise<T>, timeoutMs: number): Promise<T> {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        return await Promise.race([
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
        const { data: token } = await withTimeout(
            () => Notifications.getExpoPushTokenAsync(typeof projectId === 'string' ? { projectId } : {}),
            TOKEN_TIMEOUT_MS
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
        // The server gave this token to the active account and deleted every other user's row for it on this host.
        const host = hostKey(useAuthStore.getState().host ?? '')
        const account = useAuthStore.getState().activeAccountKey
        settleRemovals((removal) => removal.token === token && (removal.account === account || removal.host === host))
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

/** Resolves when `work` settles or after `timeoutMs`, whichever comes first. The work continues after a timeout. */
async function waitAtMost(work: Promise<unknown>, timeoutMs: number): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        await Promise.race([
            work.then(
                () => undefined,
                () => undefined
            ),
            new Promise<void>((resolve) => {
                timer = setTimeout(resolve, timeoutMs)
            }),
        ])
    } finally {
        clearTimeout(timer)
    }
}

/**
 * Reads `account`'s credentials from its own slot, never from the session. Null when the slot is gone or unreadable,
 * or when its access token has expired.
 */
async function credentialsOf(account: string): Promise<AccountCredentials | null> {
    const stored = await readAccountSession(account)
    if (!stored) {
        return null
    }
    // A refresh here could race a switch that refreshes the same slot, and a reused refresh token revokes the whole
    // token family. The account refreshes its token when it becomes active again.
    const { tokens, identity } = stored
    if (tokens.expiresAt !== null && tokens.expiresAt - Date.now() < CREDENTIALS_MARGIN_MS) {
        return null
    }
    return { host: identity.host, accessToken: tokens.accessToken }
}

/** Removes one owed registration on its account's host, with that account's token, and forgets it on success. */
async function removeOwed(removal: OwedRemoval): Promise<void> {
    const credentials = await credentialsOf(removal.account)
    if (!credentials) {
        return
    }
    await withTimeout((signal) => unregisterPushTokenFor(credentials, removal.token, { signal }), UNREGISTER_TIMEOUT_MS)
    settleRemovals((owed) => owed.account === removal.account && owed.token === removal.token)
}

async function settleOnce(): Promise<void> {
    await waitForPushHydration()
    const { status, accounts, activeAccountKey } = useAuthStore.getState()
    // The account list is complete only after restore.
    if (status !== 'signed_in') {
        return
    }
    // An account without a usable slot cannot authenticate the removal. A later registration on its host still
    // deletes its row there.
    settleRemovals((removal) => !accounts.some((account) => account.key === removal.account && !account.needsSignIn))
    for (const removal of usePushStore.getState().owed) {
        // The active account's own registration settles what it owes.
        if (removal.account === activeAccountKey) {
            continue
        }
        try {
            await removeOwed(removal)
        } catch {
            // Kept for the next launch, return to the app or switch.
        }
    }
}

/** Retries every removal that an inactive account still owes. */
export function settleOwedRemovals(): Promise<void> {
    return enqueue(settleOnce).catch(() => undefined)
}

// Calls run one after another, so a Settings tap never races the automatic run after sign in. The owed removals run
// after it in the same queue, but the caller does not wait for them.
export function syncPushRegistration(policy: PromptPolicy): Promise<void> {
    const synced = enqueue(() => syncOnce(policy)).catch(() => undefined)
    void settleOwedRemovals()
    return synced
}

/**
 * The account switch task. Only the active account stays registered, so the account that leaves owes the removal of
 * its registration until its own host confirms it. The switch waits at most `CLEANUP_WAIT_MS`.
 */
export async function releaseRegistration(next: AccountRef): Promise<void> {
    const session = sessionGeneration()
    const account = getSessionAccountKey()
    const owner = getSessionIdentity()
    const key = registrationKey()
    if (!account || !owner || !key) {
        return
    }
    // No registration for the leaving session may start or finish after this point.
    closingSession = session
    await waitAtMost(waitForPushHydration(), CLEANUP_WAIT_MS)
    const { token, registeredFor } = usePushStore.getState()
    if (!token || registeredFor !== key) {
        return
    }
    const removal: OwedRemoval = { account, host: hostKey(owner.host), token }
    // Saved before the request, so a crash or a lost response leaves the removal owed.
    oweRemoval(removal)
    usePushStore.setState({ registeredFor: null, error: null })
    // On the same host, the next account's registration of this token deletes the leaving account's row, so a request
    // here would only slow the switch. If that registration fails, the retry removes the row with this account's token.
    if (hostKey(next.host) === removal.host) {
        return
    }
    // Queued, so the removal follows a registration POST of the leaving account that is still in flight.
    await waitAtMost(
        enqueue(() => removeOwed(removal)),
        CLEANUP_WAIT_MS
    )
}

/** The inactive sign-out task: removes what the account owes while its slot still holds its tokens. */
export async function settleBeforeSignOut(account: AccountRef): Promise<void> {
    await waitAtMost(waitForPushHydration(), CLEANUP_WAIT_MS)
    if (!usePushStore.getState().owed.some((removal) => removal.account === account.key)) {
        return
    }
    await waitAtMost(
        enqueue(async () => {
            await waitForPushHydration()
            for (const removal of usePushStore.getState().owed) {
                if (removal.account === account.key) {
                    await removeOwed(removal).catch(() => undefined)
                }
            }
        }),
        CLEANUP_WAIT_MS
    )
}

/** The account-removed task. The account's credentials are gone, so nothing it owes can be removed any more. */
export function forgetOwedRemovals(account: AccountRef): void {
    settleRemovals((removal) => removal.account === account.key)
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
