import { act, renderHook, waitFor } from '@testing-library/react-native'
import * as Notifications from 'expo-notifications'

import { registerPushToken, unregisterPushToken } from '@/api/pushTokens'
import { accountKey } from '@/auth/accountKey'
import { addAccountSwitchTask, installAuthProvider, type StoredAccount, useAuthStore } from '@/auth/authStore'
import { regionForHost } from '@/auth/regions'
import { setSessionTokens, writeAccountSlot } from '@/auth/tokens'

import { releaseRegistration, settleOwedRemovals, syncPushRegistration, unregisterPush } from './pushRegistration'
import { usePushStore, waitForPushHydration } from './pushStore'
import { usePushRegistration } from './usePushRegistration'

jest.mock('expo-notifications', () => ({
    getPermissionsAsync: jest.fn(),
    requestPermissionsAsync: jest.fn(),
    getExpoPushTokenAsync: jest.fn(),
    setNotificationChannelAsync: jest.fn(),
    addPushTokenListener: jest.fn(() => ({ remove: jest.fn() })),
    IosAuthorizationStatus: { PROVISIONAL: 3 },
}))
jest.mock('expo-constants', () => ({ expoConfig: { extra: { eas: { projectId: 'test-project' } } } }))
jest.mock('@/api/pushTokens', () => ({
    ...jest.requireActual<typeof import('@/api/pushTokens')>('@/api/pushTokens'),
    registerPushToken: jest.fn(),
    unregisterPushToken: jest.fn(),
}))
jest.mock('./pushSupport', () => ({ notificationsSupported: () => true, pushUnavailableReason: () => null }))
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

const actualPushTokens = jest.requireActual<typeof import('@/api/pushTokens')>('@/api/pushTokens')
const register = registerPushToken as jest.MockedFunction<typeof registerPushToken>
const unregister = unregisterPushToken as jest.MockedFunction<typeof unregisterPushToken>
const permissions = Notifications.getPermissionsAsync as jest.MockedFunction<typeof Notifications.getPermissionsAsync>
const expoToken = Notifications.getExpoPushTokenAsync as jest.MockedFunction<typeof Notifications.getExpoPushTokenAsync>
const KEY = 'https://us.posthog.com|user-1'
const US = 'https://us.posthog.com'
const EU = 'https://eu.posthog.com'
const DEVICE = 'ExponentPushToken[device]'

async function tick(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
}

/** One PostHog instance per host, with the push token rows that `POST push_tokens/` and `unregister/` keep. */
const server = {
    /** Personal API key to its owner. A key is valid only on its owner's host. */
    keys: new Map<string, { host: string; user: string }>(),
    /** `{host}|{push token}` to the users registered for it. */
    rows: new Map<string, Set<string>>(),
    offline: new Set<string>(),
    sent: [] as { host: string; path: string; key: string }[],
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

async function answer(url: string, init: RequestInit | undefined): Promise<Response> {
    const { origin, pathname } = new URL(url)
    const key = (init?.headers as Record<string, string> | undefined)?.Authorization?.replace('Bearer ', '') ?? ''
    server.sent.push({ host: origin, path: pathname, key })
    if (server.offline.has(origin)) {
        throw new TypeError('Network request failed')
    }
    const owner = server.keys.get(key)
    if (!owner || owner.host !== origin) {
        return json(401, { detail: 'Invalid personal API key.' })
    }
    const token = typeof init?.body === 'string' ? (JSON.parse(init.body) as { token: string }).token : ''
    const row = `${origin}|${token}`
    if (pathname === '/api/users/@me/push_tokens/') {
        // The server gives the token to the caller and deletes every other user's row for it on this instance.
        server.rows.set(row, new Set([owner.user]))
        return json(201, {})
    }
    if (pathname === '/api/users/@me/push_tokens/unregister/') {
        server.rows.get(row)?.delete(owner.user)
        return new Response(null, { status: 204 })
    }
    return json(404, {})
}

/** `{host} {user}` for every account the device token is registered for. */
function registrations(): string[] {
    return [...server.rows.entries()].flatMap(([row, users]) =>
        row.endsWith(`|${DEVICE}`) ? [...users].map((user) => `${row.split('|')[0]} ${user}`) : []
    )
}

function pushRequests(): string[] {
    return server.sent
        .filter(({ path }) => path.includes('/push_tokens/'))
        .map(
            ({ host, path, key }) =>
                `${host} ${path.endsWith('/unregister/') ? 'unregister' : 'register'} ${server.keys.get(key)?.user}`
        )
}

async function storedAccount(host: string, user: string, lastUsedAt: number): Promise<StoredAccount> {
    const key = await accountKey(host, user)
    await writeAccountSlot(
        key,
        {
            kind: 'personal_api_key',
            accessToken: `${user}-key`,
            refreshToken: null,
            expiresAt: null,
            grantedScopes: null,
            requestedScopes: null,
        },
        { host, clientId: null, method: 'personal_api_key', userUuid: user }
    )
    server.keys.set(`${user}-key`, { host, user })
    return {
        key,
        host,
        clientId: null,
        method: 'personal_api_key',
        region: regionForHost(host),
        userUuid: user,
        user: { uuid: user, distinctId: user, email: `${user}@example.com`, name: user },
        organizations: [],
        projects: [],
        projectId: null,
        needsSignIn: false,
        lastUsedAt,
    }
}

function activate(active: StoredAccount, accounts: StoredAccount[]): void {
    setSessionTokens(
        {
            kind: 'personal_api_key',
            accessToken: `${active.userUuid}-key`,
            refreshToken: null,
            expiresAt: null,
            grantedScopes: null,
            requestedScopes: null,
        },
        { host: active.host, clientId: null, method: 'personal_api_key', userUuid: active.userUuid },
        active.key
    )
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        host: active.host,
        clientId: null,
        method: 'personal_api_key',
        user: active.user,
        accounts,
        activeAccountKey: active.key,
    })
}

describe('push registration across session transitions', () => {
    afterEach(() => jest.useRealTimers())

    beforeEach(async () => {
        await waitForPushHydration()
        setSessionTokens({
            kind: 'personal_api_key',
            accessToken: 'session-token',
            refreshToken: null,
            expiresAt: null,
            grantedScopes: null,
            requestedScopes: null,
        })
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://us.posthog.com',
            user: { uuid: 'user-1', distinctId: 'user-1', email: 'user@example.com', name: 'User' },
            accounts: [],
            activeAccountKey: null,
        })
        usePushStore.setState({
            permission: 'unknown',
            canAskAgain: true,
            token: null,
            registeredFor: null,
            owed: [],
            prompted: false,
            registering: false,
            error: null,
        })
        register.mockReset().mockResolvedValue(undefined)
        unregister.mockReset().mockResolvedValue(undefined)
        permissions.mockReset().mockResolvedValue({ granted: true, status: 'granted', canAskAgain: true } as never)
        expoToken.mockReset().mockResolvedValue({ data: 'ExponentPushToken[new]' } as never)
    })

    test.each(['resolve', 'reject'] as const)(
        'a stalled token request stops loading, allows a retry and ignores a late %s',
        async (outcome) => {
            jest.useFakeTimers()
            let finishToken!: (token: Notifications.ExpoPushToken) => void
            let failToken!: (error: Error) => void
            expoToken.mockImplementationOnce(
                () =>
                    new Promise((resolve, reject) => {
                        finishToken = resolve
                        failToken = reject
                    })
            )
            const syncing = syncPushRegistration('never')
            await jest.advanceTimersByTimeAsync(0)
            expect(usePushStore.getState().registering).toBe(true)

            await jest.advanceTimersByTimeAsync(15_000)
            expect(usePushStore.getState()).toMatchObject({
                registering: false,
                token: null,
                error: 'Push request timed out',
            })
            await syncing
            expect(register).not.toHaveBeenCalled()

            await syncPushRegistration('always')
            expect(usePushStore.getState()).toMatchObject({
                registering: false,
                token: 'ExponentPushToken[new]',
                error: null,
            })
            if (outcome === 'resolve') {
                finishToken({ type: 'expo', data: 'ExponentPushToken[late]' })
            } else {
                failToken(new Error('Late token failure'))
            }
            await jest.advanceTimersByTimeAsync(0)
            expect(register).toHaveBeenCalledTimes(1)
            expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[new]', error: null })
        }
    )

    test('sign out completes after a stalled token request times out', async () => {
        jest.useFakeTimers()
        expoToken.mockImplementationOnce(() => new Promise(() => undefined))
        const syncing = syncPushRegistration('never')
        await jest.advanceTimersByTimeAsync(0)
        const cleanup = unregisterPush()

        await jest.advanceTimersByTimeAsync(15_000)
        expect(usePushStore.getState().registering).toBe(false)
        await syncing
        const recover = await cleanup
        expect(register).not.toHaveBeenCalled()
        expect(usePushStore.getState()).toMatchObject({ token: null, registeredFor: null, error: null })
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_out', signedIn: false })
        recover()
        await jest.advanceTimersByTimeAsync(0)
    })

    test('sign out waits for a first registration POST and then deletes its possibly accepted token', async () => {
        let finishPost: () => void = () => undefined
        let postStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            postStarted = resolve
        })
        register.mockImplementationOnce(
            () =>
                new Promise<void>((resolve) => {
                    postStarted()
                    finishPost = resolve
                })
        )
        const syncing = syncPushRegistration('never')
        await started
        const cleanup = unregisterPush()
        expect(unregister).not.toHaveBeenCalled()
        finishPost()
        await syncing
        const recover = await cleanup
        expect(unregister).toHaveBeenCalledWith('ExponentPushToken[new]', expect.anything())
        expect(usePushStore.getState().token).toBeNull()
        recover()
    })

    test('a failed POST retains the attempted token for cleanup and Settings retry', async () => {
        register.mockRejectedValueOnce(new Error('Network response lost'))
        await syncPushRegistration('never')
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[new]', registeredFor: KEY })
        expect(usePushStore.getState().error).toBeTruthy()

        await syncPushRegistration('always')
        expect(register).toHaveBeenCalledTimes(2)
        expect(usePushStore.getState()).toMatchObject({
            token: 'ExponentPushToken[new]',
            registeredFor: KEY,
            error: null,
        })
    })

    test('a failed rotation delete retains the old token and retries before registering the new one', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        unregister.mockRejectedValueOnce(new Error('Offline'))
        await syncPushRegistration('never')
        expect(register).not.toHaveBeenCalled()
        expect(usePushStore.getState().token).toBe('ExponentPushToken[old]')
        expect(usePushStore.getState().error).toBeTruthy()

        await syncPushRegistration('never')
        expect(unregister).toHaveBeenCalledTimes(2)
        expect(register).toHaveBeenCalledTimes(1)
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[new]', error: null })
    })

    test('a session ending during rotation delete never registers the next token', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        let finishDelete: () => void = () => undefined
        let deleteStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            deleteStarted = resolve
        })
        unregister.mockImplementationOnce(
            () =>
                new Promise<void>((resolve) => {
                    deleteStarted()
                    finishDelete = resolve
                })
        )
        const syncing = syncPushRegistration('never')
        await started
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_out', signedIn: false })
        finishDelete()
        await syncing
        expect(register).not.toHaveBeenCalled()
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[old]', registering: false })
    })

    test('failed cleanup preserves the token and a later attempt can finish', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        unregister.mockRejectedValueOnce(new Error('Offline'))
        await expect(unregisterPush()).rejects.toThrow('try again')
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        const recover = await unregisterPush()
        expect(unregister).toHaveBeenCalledTimes(2)
        expect(usePushStore.getState().token).toBeNull()
        recover()
        await tick()
    })

    describe('with several accounts', () => {
        let unmount: (() => void) | null = null

        beforeEach(() => {
            register.mockImplementation(actualPushTokens.registerPushToken)
            unregister.mockImplementation(actualPushTokens.unregisterPushToken)
            expoToken.mockResolvedValue({ type: 'expo', data: DEVICE })
            globalThis.fetch = jest.fn(answer) as unknown as typeof fetch
            mockSecureItems.clear()
            server.keys.clear()
            server.rows.clear()
            server.offline.clear()
            server.sent = []
            installAuthProvider()
        })

        afterEach(() => {
            unmount?.()
            unmount = null
        })

        /** Every request carried the key of an account on the host it went to, so no token reached another host. */
        function expectEveryKeyOnItsOwnHost(): void {
            expect(server.sent.filter(({ host, key }) => server.keys.get(key)?.host !== host)).toEqual([])
        }

        async function signedInAsAda(bobHost: string): Promise<{ ada: StoredAccount; bob: StoredAccount }> {
            const ada = await storedAccount(US, 'ada', 2)
            const bob = await storedAccount(bobHost, 'bob', 1)
            activate(ada, [ada, bob])
            unmount = renderHook(usePushRegistration).unmount
            await waitFor(() => expect(registrations()).toEqual([`${US} ada`]))
            return { ada, bob }
        }

        test.each([
            {
                name: 'on another host',
                bobHost: EU,
                requests: [`${US} register ada`, `${US} unregister ada`, `${EU} register bob`],
            },
            // Bob's registration deletes Ada's row on the server, so the switch sends no unregister.
            { name: 'on the same host', bobHost: US, requests: [`${US} register ada`, `${US} register bob`] },
        ])('a switch to an account $name leaves only that account registered', async ({ bobHost, requests }) => {
            const { bob } = await signedInAsAda(bobHost)

            await act(() => useAuthStore.getState().switchAccount(bob.key, { from: 'settings' }))

            await waitFor(() => expect(registrations()).toEqual([`${bobHost} bob`]))
            expect(pushRequests()).toEqual(requests)
            expect(usePushStore.getState().owed).toEqual([])
            expectEveryKeyOnItsOwnHost()
        })

        test.each([
            { name: 'a later retry', settle: (): Promise<void> => settleOwedRemovals(), accounts: 2 },
            {
                name: 'signing out of that account',
                settle: (ada: StoredAccount): Promise<void> => useAuthStore.getState().signOutAccount(ada.key),
                accounts: 1,
            },
        ])(
            'an offline removal never fails the switch, and $name removes it with that account’s own key',
            async ({ settle, accounts }) => {
                const { ada, bob } = await signedInAsAda(EU)
                server.offline.add(US)

                await act(() => useAuthStore.getState().switchAccount(bob.key, { from: 'settings' }))

                expect(useAuthStore.getState().activeAccountKey).toBe(bob.key)
                await waitFor(() => expect(registrations()).toEqual([`${US} ada`, `${EU} bob`]))
                // Lets the retry that follows Bob's registration fail while the host is still offline.
                await act(() => settleOwedRemovals())
                expect(usePushStore.getState().owed).toEqual([{ account: ada.key, host: US, token: DEVICE }])

                server.offline.delete(US)
                await act(() => settle(ada))

                expect(registrations()).toEqual([`${EU} bob`])
                expect(usePushStore.getState().owed).toEqual([])
                expect(useAuthStore.getState().accounts).toHaveLength(accounts)
                expectEveryKeyOnItsOwnHost()
            }
        )

        test('a removal that hangs holds the switch for at most the cleanup wait and stays owed', async () => {
            const ada = await storedAccount(US, 'ada', 2)
            const bob = await storedAccount(EU, 'bob', 1)
            activate(ada, [ada, bob])
            usePushStore.setState({ token: DEVICE, registeredFor: `${US}|ada` })
            const stopSwitchTask = addAccountSwitchTask(releaseRegistration)
            globalThis.fetch = jest.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch
            jest.useFakeTimers()
            try {
                let switched = false
                void useAuthStore
                    .getState()
                    .switchAccount(bob.key, { from: 'settings' })
                    .then(() => {
                        switched = true
                    })

                await jest.advanceTimersByTimeAsync(2_500)

                expect(switched).toBe(true)
                expect(useAuthStore.getState().activeAccountKey).toBe(bob.key)
                expect(usePushStore.getState()).toMatchObject({
                    registeredFor: null,
                    owed: [{ account: ada.key, host: US, token: DEVICE }],
                })
                // The unregister request reaches its own deadline and leaves the removal owed.
                await jest.advanceTimersByTimeAsync(4_000)
                expect(usePushStore.getState().owed).toHaveLength(1)
            } finally {
                stopSwitchTask()
            }
        })
    })
})
