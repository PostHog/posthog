import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'
import * as SecureStore from 'expo-secure-store'

import { accountKey } from '@/auth/accountKey'
import { installAuthProvider, type StoredAccount, useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'
import { aiConsentKey, useAiConsentStore } from '@/features/chat/aiConsentStore'
import { useChatFeedbackStore } from '@/features/chat/chatFeedbackStore'
import '@/features/snooze/hooks'
import { type SnoozeEntry, snoozeKey } from '@/features/snooze/snoozeEntries'
import { useSnoozeStore } from '@/features/snooze/snoozeStore'
import { accountPinPrefs, usePinPrefs } from '@/features/views/pinPrefsStore'
import { useDeviceRecent } from '@/features/views/recentStore'

const mockSecureItems = new Map<string, string>()
jest.mock('expo-secure-store', () => ({
    getItemAsync: async (key: string) => mockSecureItems.get(key) ?? null,
    setItemAsync: async (key: string, value: string) => {
        mockSecureItems.set(key, value)
    },
    deleteItemAsync: async (key: string) => {
        mockSecureItems.delete(key)
    },
}))
jest.mock('expo-crypto', () => ({
    CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
    digestStringAsync: async (_algorithm: string, value: string) => Buffer.from(value).toString('hex'),
}))
jest.mock('expo-notifications', () => ({
    cancelScheduledNotificationAsync: jest.fn(async () => undefined),
}))

const HOST = 'https://us.posthog.com'
const OTHER_HOST = 'https://eu.posthog.com'
const SCOPE = { host: HOST, projectId: 2 }
const PROJECT = `${HOST}|2`
const LATER = new Date(Date.now() + 86_400_000).toISOString()

function account(user: string): StoredAccount {
    return {
        key: `${user}-key`,
        host: HOST,
        clientId: 'example-client',
        method: 'oauth',
        region: 'us',
        userUuid: user,
        user: { uuid: user, distinctId: user, email: `${user}@example.com`, name: user },
        organizations: [],
        projects: [],
        projectId: 2,
        needsSignIn: false,
        lastUsedAt: 1,
    }
}

const ADA = account('ada')
const BOB = account('bob')

function snooze(reminder: string): SnoozeEntry {
    return { kind: 'until', until: LATER, at: new Date().toISOString(), notificationId: reminder }
}

function feedbackKey(owner: StoredAccount): string {
    return `live|${owner.host}|${owner.userUuid}|2|sandbox|trace-1`
}

const STORES = [
    {
        name: 'snoozes',
        write: (owner: StoredAccount): void =>
            useSnoozeStore
                .getState()
                .put(owner.key, snoozeKey(SCOPE, 'report-1'), snooze(`reminder-${owner.userUuid}`)),
        read: (owner: StoredAccount): unknown =>
            useSnoozeStore.getState().accounts[owner.key]?.[snoozeKey(SCOPE, 'report-1')],
    },
    {
        name: 'pin prefs',
        write: (owner: StoredAccount): void =>
            usePinPrefs.getState().setDisplay(owner.key, PROJECT, 'pin-1', { mode: 'chart' }),
        read: (owner: StoredAccount): unknown => accountPinPrefs(owner.key, PROJECT).display['pin-1'],
    },
    {
        name: 'recent views',
        write: (owner: StoredAccount): void =>
            useDeviceRecent.getState().record(owner.key, PROJECT, {
                kind: 'insight',
                ref: 'insight-1',
                name: 'Signups',
                viewedAt: new Date().toISOString(),
            }),
        read: (owner: StoredAccount): unknown => useDeviceRecent.getState().accounts[owner.key]?.[PROJECT]?.[0],
    },
    {
        name: 'AI consent',
        write: (owner: StoredAccount): void =>
            useAiConsentStore.getState().accept(aiConsentKey(owner.host, owner.userUuid)),
        read: (owner: StoredAccount): unknown =>
            useAiConsentStore.getState().accepted[aiConsentKey(owner.host, owner.userUuid)],
    },
    {
        name: 'chat feedback',
        write: (owner: StoredAccount): void => {
            useChatFeedbackStore.getState().rate(feedbackKey(owner), 'good')
        },
        read: (owner: StoredAccount): unknown => useChatFeedbackStore.getState().responses[feedbackKey(owner)],
    },
]

describe('account data on a device with several accounts', () => {
    beforeEach(() => {
        mockSecureItems.clear()
        jest.mocked(Notifications.cancelScheduledNotificationAsync).mockClear()
        useSnoozeStore.setState({ accounts: {}, legacy: null })
        usePinPrefs.setState({ accounts: {}, legacy: null })
        useDeviceRecent.setState({ accounts: {}, legacy: null })
        useAiConsentStore.setState({ accepted: {} })
        useChatFeedbackStore.setState({ responses: {}, hydrated: true })
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_in', signedIn: true, accounts: [ADA, BOB], activeAccountKey: ADA.key })
    })

    test.each(STORES)(
        '$name of one account stay out of another account on the same host and project, and leave with it only',
        async ({ write, read }) => {
            write(ADA)
            expect(read(BOB)).toBeUndefined()
            write(BOB)

            await useAuthStore.getState().signOutAccount(BOB.key)

            expect(read(BOB)).toBeUndefined()
            expect(read(ADA)).toBeDefined()
        }
    )

    test("removing an account cancels only that account's snooze reminders", async () => {
        STORES[0]?.write(ADA)
        STORES[0]?.write(BOB)

        await useAuthStore.getState().signOutAccount(BOB.key)

        expect(jest.mocked(Notifications.cancelScheduledNotificationAsync).mock.calls).toEqual([['reminder-bob']])
    })

    test('an upgrade gives saved snoozes, pin prefs and recent views to the restored account on their host', async () => {
        const prefs = { rank: { 'pin-1': 0 }, display: {} }
        const kept = snooze('reminder-kept')
        const recent = [{ kind: 'insight', ref: 'insight-1', name: 'Signups', viewedAt: new Date().toISOString() }]
        // The single-account app stored each map for whoever was signed in, so these are what an upgrade finds.
        await AsyncStorage.multiSet([
            [
                'posthog-mobile-snoozes',
                JSON.stringify({
                    version: 0,
                    state: {
                        entries: {
                            [snoozeKey(SCOPE, 'report-1')]: kept,
                            [snoozeKey({ host: OTHER_HOST, projectId: 2 }, 'report-2')]: snooze('reminder-dropped'),
                        },
                    },
                }),
            ],
            [
                'views-pin-prefs:v2',
                JSON.stringify({ version: 0, state: { projects: { [PROJECT]: prefs, [`${OTHER_HOST}|2`]: prefs } } }),
            ],
            [
                'views-recent:v1',
                JSON.stringify({ version: 0, state: { entries: { [PROJECT]: recent, [`${OTHER_HOST}|2`]: recent } } }),
            ],
            ['posthog-mobile-auth', JSON.stringify({ version: 1, state: { host: HOST, region: 'us' } })],
        ])
        await Promise.all([
            useSnoozeStore.persist.rehydrate(),
            usePinPrefs.persist.rehydrate(),
            useDeviceRecent.persist.rehydrate(),
            useAuthStore.persist.rehydrate(),
        ])
        await SecureStore.setItemAsync(
            'posthog_mobile_session',
            JSON.stringify({
                version: 1,
                identity: { host: HOST, clientId: 'example-client', method: 'oauth', userUuid: 'ada' },
                tokens: {
                    kind: 'oauth',
                    accessToken: 'ada-access',
                    refreshToken: 'ada-refresh',
                    expiresAt: Date.now() + 86_400_000 * 7,
                    grantedScopes: null,
                    requestedScopes: null,
                },
            })
        )
        globalThis.fetch = jest.fn(async () => {
            throw new TypeError('Offline')
        }) as typeof fetch
        installAuthProvider()

        await useAuthStore.getState().restore()

        const key = await accountKey(HOST, 'ada')
        await waitFor(() => expect(useSnoozeStore.getState().legacy).toBeNull())
        await waitFor(() => expect(usePinPrefs.getState().legacy).toBeNull())
        await waitFor(() => expect(useDeviceRecent.getState().legacy).toBeNull())
        expect(useSnoozeStore.getState().accounts).toEqual({
            [key]: { [snoozeKey(SCOPE, 'report-1')]: kept },
        })
        await waitFor(() =>
            expect(Notifications.cancelScheduledNotificationAsync).toHaveBeenCalledWith('reminder-dropped')
        )
        expect(usePinPrefs.getState().accounts).toEqual({ [key]: { [PROJECT]: prefs } })
        expect(useDeviceRecent.getState().accounts).toEqual({ [key]: { [PROJECT]: recent } })
    })
})
