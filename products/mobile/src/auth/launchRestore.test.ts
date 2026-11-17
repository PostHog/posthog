import { AppState, type AppStateStatus } from 'react-native'

import type * as AuthStore from './authStore'

const mockSecureItems = new Map<string, string>()
const mockUnreadable = new Set<string>()
const mockAsyncItems = new Map<string, string>()
const mockPromptOptions: unknown[] = []

jest.mock('@react-native-async-storage/async-storage', () => ({
    __esModule: true,
    default: {
        getItem: async (key: string) => mockAsyncItems.get(key) ?? null,
        setItem: async (key: string, value: string) => {
            mockAsyncItems.set(key, value)
        },
        removeItem: async (key: string) => {
            mockAsyncItems.delete(key)
        },
    },
}))
jest.mock('expo-secure-store', () => ({
    getItemAsync: async (key: string) => {
        if (mockUnreadable.has(key)) {
            throw new Error('User interaction is not allowed.')
        }
        return mockSecureItems.get(key) ?? null
    },
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
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))
jest.mock('expo-auth-session', () => ({
    AuthRequest: jest.fn().mockImplementation(() => ({
        redirectUri: 'posthog://callback',
        codeVerifier: 'fake-verifier',
        promptAsync: async (_discovery: unknown, options: unknown) => {
            mockPromptOptions.push(options)
            return { type: 'success', params: { code: 'fake-code' } }
        },
    })),
    makeRedirectUri: () => 'posthog://callback',
}))

const US = 'https://us.posthog.com'
const KEYS = {
    ada: Buffer.from(JSON.stringify([US, 'ada'])).toString('hex'),
    bob: Buffer.from(JSON.stringify([US, 'bob'])).toString('hex'),
}
const SLOT = (key: string): string => `posthog_mobile_session.${key}`

const sent: string[] = []

function json(body: unknown): Response {
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function me(user: string): Response {
    return json({
        id: 7,
        uuid: user,
        distinct_id: `${user}-distinct`,
        email: `${user}@example.com`,
        first_name: '',
        last_name: '',
        team: null,
        organization: null,
        organizations: [],
    })
}

/** Ada's browser session signs her in again, and every bearer token belongs to the user its name starts with. */
async function answer(url: string, init?: RequestInit): Promise<Response> {
    const body = typeof init?.body === 'string' ? init.body : ''
    sent.push(`${new URL(url).pathname} ${body}`)
    if (url.endsWith('/oauth/token')) {
        return json({ access_token: 'ada-access-new', refresh_token: 'ada-refresh-new', expires_in: 604800 })
    }
    if (url.endsWith('/oauth/revoke')) {
        return json({})
    }
    const bearer = (init?.headers as Record<string, string> | undefined)?.Authorization ?? ''
    return me(bearer.includes('bob') ? 'bob' : 'ada')
}

function storeSlot(user: 'ada' | 'bob'): void {
    mockSecureItems.set(
        SLOT(KEYS[user]),
        JSON.stringify({
            version: 1,
            identity: { host: US, clientId: 'example-client', method: 'oauth', userUuid: user },
            tokens: {
                kind: 'oauth',
                accessToken: `${user}-access`,
                refreshToken: `${user}-refresh`,
                expiresAt: Date.now() + 604_800_000,
                grantedScopes: null,
                requestedScopes: null,
            },
        })
    )
}

function storedAccount(user: 'ada' | 'bob'): AuthStore.StoredAccount {
    return {
        key: KEYS[user],
        host: US,
        clientId: 'example-client',
        method: 'oauth',
        region: 'us',
        userUuid: user,
        user: { uuid: user, distinctId: `${user}-distinct`, email: `${user}@example.com`, name: user },
        organizations: [],
        projects: [],
        projectId: null,
        needsSignIn: false,
        lastUsedAt: 1,
    }
}

function persistAuth(state: Partial<AuthStore.AuthState>): void {
    mockAsyncItems.set('posthog-mobile-auth', JSON.stringify({ version: 2, state }))
}

/** A fresh process: new modules, the same keychain and AsyncStorage. */
function launch(): { auth: typeof AuthStore; foreground: () => void } {
    let auth!: typeof AuthStore
    let onAppState: ((state: AppStateStatus) => void) | undefined
    const subscribe = jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
        onAppState = listener
        return { remove: () => undefined }
    })
    jest.isolateModules(() => {
        auth = require('./authStore')
    })
    auth.installAuthProvider()
    subscribe.mockRestore()
    return { auth, foreground: () => onAppState?.('active') }
}

async function until(condition: () => boolean): Promise<void> {
    for (let waited = 0; !condition(); waited += 5) {
        if (waited > 2_000) {
            throw new Error('Timed out waiting for the condition')
        }
        await new Promise((resolve) => setTimeout(resolve, 5))
    }
}

describe('launch restore', () => {
    beforeEach(() => {
        mockSecureItems.clear()
        mockUnreadable.clear()
        mockAsyncItems.clear()
        mockPromptOptions.length = 0
        sent.length = 0
        globalThis.fetch = jest.fn(answer) as unknown as typeof fetch
        // Loading expo installs its own fetch as the global one, so its mock answers too.
        ;(jest.requireMock('expo/fetch') as { fetch: jest.Mock }).fetch.mockImplementation(answer)
    })

    test('a launch that cannot read the active slot keeps the account, and a later foreground restores it', async () => {
        storeSlot('ada')
        mockSecureItems.set(
            'posthog_mobile_accounts',
            JSON.stringify({ version: 1, active: KEYS.ada, keys: [KEYS.ada] })
        )
        persistAuth({ accounts: [storedAccount('ada')], activeAccountKey: KEYS.ada })
        mockUnreadable.add(SLOT(KEYS.ada))
        const { auth, foreground } = launch()
        let launched: AuthStore.AccountRef | null | 'pending' = 'pending'
        void auth.launchAccount().then((account) => {
            launched = account
        })

        await auth.useAuthStore.getState().restore()

        expect(auth.useAuthStore.getState()).toMatchObject({ status: 'signed_out', unreadableAccountKeys: [KEYS.ada] })
        expect(auth.useAuthStore.getState().accounts).toEqual([expect.objectContaining({ needsSignIn: false })])
        expect(mockSecureItems.has(SLOT(KEYS.ada))).toBe(true)
        expect(launched).toBe('pending')

        mockUnreadable.clear()
        foreground()
        await until(() => auth.useAuthStore.getState().status === 'signed_in')

        expect(auth.useAuthStore.getState()).toMatchObject({ activeAccountKey: KEYS.ada, unreadableAccountKeys: [] })
        await until(() => launched !== 'pending')
        expect(launched).toEqual({ key: KEYS.ada, host: US, userUuid: 'ada' })
    })

    test('while its slot cannot be read, a sign-in to that account uses the browser session and replaces the slot', async () => {
        storeSlot('ada')
        mockSecureItems.set(
            'posthog_mobile_accounts',
            JSON.stringify({ version: 1, active: KEYS.ada, keys: [KEYS.ada] })
        )
        persistAuth({ accounts: [storedAccount('ada')], activeAccountKey: KEYS.ada })
        mockUnreadable.add(SLOT(KEYS.ada))
        const { auth } = launch()
        await auth.useAuthStore.getState().restore()

        await auth.useAuthStore.getState().signIn(US, 'example-client')

        expect(mockPromptOptions).toEqual([{ preferEphemeralSession: false }])
        expect(auth.useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: KEYS.ada })
        expect(JSON.parse(mockSecureItems.get(SLOT(KEYS.ada)) ?? '{}')).toMatchObject({
            tokens: { refreshToken: 'ada-refresh-new' },
        })
        expect(sent.filter((request) => request.startsWith('/oauth/revoke'))).toEqual([])
    })

    test('a removal that failed before is finished at launch instead of restoring the account', async () => {
        storeSlot('ada')
        storeSlot('bob')
        mockSecureItems.set(
            'posthog_mobile_accounts',
            JSON.stringify({ version: 1, active: KEYS.bob, keys: [KEYS.ada, KEYS.bob] })
        )
        persistAuth({ accounts: [storedAccount('bob')], activeAccountKey: KEYS.bob, pendingSlotRemovals: [KEYS.ada] })
        const { auth } = launch()

        await auth.useAuthStore.getState().restore()

        expect(auth.useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            activeAccountKey: KEYS.bob,
            pendingSlotRemovals: [],
        })
        expect(auth.useAuthStore.getState().accounts.map((account) => account.key)).toEqual([KEYS.bob])
        expect(mockSecureItems.has(SLOT(KEYS.ada))).toBe(false)
        expect(JSON.parse(mockSecureItems.get('posthog_mobile_accounts') ?? '{}')).toMatchObject({ keys: [KEYS.bob] })
        await until(() => sent.some((request) => request.startsWith('/oauth/revoke')))
        expect(sent.filter((request) => request.startsWith('/oauth/revoke'))).toEqual([
            expect.stringContaining('token=ada-refresh'),
        ])
    })
})
