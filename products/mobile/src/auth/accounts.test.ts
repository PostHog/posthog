import { apiJson, NotSignedInError } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { type AnalyticsEvent, setAnalyticsClient } from '@/lib/analytics'

import type { AccountRef } from './accountKey'
import { accountKey } from './accountKey'
import {
    AccountAlreadyAddedError,
    AccountNeedsSignInError,
    addAccountRemovedTask,
    installAuthProvider,
    refreshAccessToken,
    useAuthStore,
} from './authStore'
import { getSessionTokens, sessionGeneration, setSessionTokens } from './tokens'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))
const mockPromptOptions: unknown[] = []
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

const US = 'https://us.posthog.com'
const EU = 'https://eu.posthog.com'
const CLIENT = 'example-client'
// First-party access tokens last a week, so a switch starts no foreground refresh on its own.
const WEEK_S = 7 * 24 * 3600

interface Sent {
    url: string
    /** Every credential the request carried: its bearer token and any token in its body. */
    credentials: string[]
}

/** A PostHog instance per host that rotates refresh tokens and knows which user owns each token. */
const server = {
    browserUser: 'ada',
    expiresIn: WEEK_S,
    unreachable: false,
    owners: new Map<string, { host: string; user: string }>(),
    refused: new Set<string>(),
    sent: [] as Sent[],
    issued: 0,
    heldRefresh: null as null | { reached: () => void; release: Promise<void> },
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function issue(host: string, user: string): Response {
    server.issued += 1
    const access = `${user}-access-${server.issued}`
    const refresh = `${user}-refresh-${server.issued}`
    server.owners.set(access, { host, user })
    server.owners.set(refresh, { host, user })
    return json(200, { access_token: access, refresh_token: refresh, expires_in: server.expiresIn })
}

async function answer(url: string, init: RequestInit | undefined): Promise<Response> {
    const { origin, pathname } = new URL(url)
    const bearer = (init?.headers as Record<string, string> | undefined)?.Authorization?.replace('Bearer ', '')
    const body = typeof init?.body === 'string' ? init.body : ''
    const parsed: Record<string, string> = body.startsWith('{')
        ? (JSON.parse(body) as Record<string, string>)
        : Object.fromEntries(new URLSearchParams(body))
    const fields = { grant_type: '', refresh_token: '', token: '', ...parsed }
    server.sent.push({
        url,
        credentials: [bearer, fields.refresh_token, fields.token].filter((value): value is string => !!value),
    })
    if (server.unreachable) {
        throw new TypeError('Network request failed')
    }
    if (pathname === '/oauth/token' && fields.grant_type === 'authorization_code') {
        return issue(origin, server.browserUser)
    }
    if (pathname === '/oauth/token') {
        const owner = server.owners.get(fields.refresh_token)
        if (!owner || owner.host !== origin || server.refused.has(fields.refresh_token)) {
            return json(400, { error: 'invalid_grant' })
        }
        server.refused.add(fields.refresh_token)
        const rotated = issue(origin, owner.user)
        // The server has rotated the pair; only its response is late.
        if (server.heldRefresh) {
            const held = server.heldRefresh
            server.heldRefresh = null
            held.reached()
            await held.release
        }
        return rotated
    }
    if (pathname === '/oauth/revoke') {
        server.refused.add(fields.token)
        return json(200, {})
    }
    if (pathname === '/api/users/@me/') {
        const owner = bearer ? server.owners.get(bearer) : undefined
        if (!owner || owner.host !== origin || server.refused.has(bearer as string)) {
            return json(401, { detail: 'expired' })
        }
        return json(200, {
            id: 7,
            uuid: owner.user,
            distinct_id: `${owner.user}-distinct`,
            email: `${owner.user}@example.com`,
            first_name: '',
            last_name: '',
            team: null,
            organization: null,
            organizations: [],
        })
    }
    return json(404, {})
}

/** Holds the next refresh at the server until `release` runs. */
function holdNextRefresh(): { reached: Promise<void>; release: () => void } {
    let release: () => void = () => undefined
    let reached: () => void = () => undefined
    const reachedPromise = new Promise<void>((resolve) => {
        reached = resolve
    })
    server.heldRefresh = {
        reached,
        release: new Promise<void>((resolve) => {
            release = resolve
        }),
    }
    return { reached: reachedPromise, release: () => release() }
}

async function signIn(host: string, user: string): Promise<string> {
    server.browserUser = user
    await useAuthStore.getState().signIn(host, CLIENT)
    return accountKey(host, user)
}

function slot(key: string): { tokens: { accessToken: string; refreshToken: string } } | null {
    const raw = mockSecureItems.get(`posthog_mobile_session.${key}`)
    return raw ? JSON.parse(raw) : null
}

function revoked(): string[] {
    return server.sent.filter(({ url }) => url.endsWith('/oauth/revoke')).flatMap(({ credentials }) => credentials)
}

function ownerHostOf(token: string): string | undefined {
    return server.owners.get(token)?.host
}

describe('several accounts on one device', () => {
    const removed: AccountRef[] = []
    const stopRemoved = addAccountRemovedTask((account) => {
        removed.push(account)
    })

    afterAll(() => {
        stopRemoved()
    })

    beforeEach(() => {
        globalThis.fetch = jest.fn(answer) as unknown as typeof fetch
        mockSecureItems.clear()
        mockPromptOptions.length = 0
        removed.length = 0
        Object.assign(server, {
            browserUser: 'ada',
            expiresIn: WEEK_S,
            unreachable: false,
            heldRefresh: null,
            sent: [],
        })
        server.owners.clear()
        server.refused.clear()
        queryClient.clear()
        setSessionTokens(null)
        useAuthStore.setState({
            status: 'signed_out',
            signedIn: false,
            host: null,
            clientId: null,
            method: null,
            user: null,
            projectId: null,
            accounts: [],
            activeAccountKey: null,
            freshLoginNext: false,
            signedOutReason: null,
        })
        installAuthProvider()
    })

    afterEach(() => {
        setAnalyticsClient(null)
    })

    async function expireActiveSession(): Promise<void> {
        server.refused.add(getSessionTokens()?.accessToken as string)
        server.refused.add(getSessionTokens()?.refreshToken as string)
        await expect(apiJson('/api/users/@me/')).rejects.toBeInstanceOf(NotSignedInError)
    }

    test.each([
        {
            name: 'with no account and no sign-out',
            before: async (): Promise<void> => undefined,
            fresh: false,
            ephemeral: false,
        },
        {
            name: 'while another account is signed in',
            before: async (): Promise<void> => {
                await signIn(EU, 'bob')
            },
            fresh: false,
            ephemeral: true,
        },
        {
            name: 'when the user asks for a different account',
            before: async (): Promise<void> => undefined,
            fresh: true,
            ephemeral: true,
        },
        {
            name: 'after the user signed out',
            before: async (): Promise<void> => {
                await signIn(US, 'ada')
                await useAuthStore.getState().signOut()
            },
            fresh: false,
            ephemeral: true,
        },
        {
            name: 'after an expiry that followed a sign-in after a sign-out',
            before: async (): Promise<void> => {
                await signIn(US, 'ada')
                await useAuthStore.getState().signOut()
                await signIn(US, 'ada')
                await expireActiveSession()
            },
            fresh: false,
            ephemeral: false,
        },
    ])('a sign-in $name keeps the browser session out: $ephemeral', async ({ before, fresh, ephemeral }) => {
        await before()
        mockPromptOptions.length = 0
        server.browserUser = 'ada'

        await useAuthStore.getState().signIn(US, CLIENT, fresh ? { freshLogin: true } : undefined)

        expect(mockPromptOptions).toEqual([{ preferEphemeralSession: ephemeral }])
    })

    test('adding an account keeps the first one signed in, with its slot, metadata and refresh token', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')

        expect(mockPromptOptions).toEqual([{ preferEphemeralSession: false }, { preferEphemeralSession: true }])
        expect(useAuthStore.getState()).toMatchObject({ activeAccountKey: bob, host: EU, user: { uuid: 'bob' } })
        expect(useAuthStore.getState().accounts).toEqual([
            expect.objectContaining({
                key: ada,
                host: US,
                user: expect.objectContaining({ uuid: 'ada' }),
                needsSignIn: false,
            }),
            expect.objectContaining({ key: bob, host: EU, needsSignIn: false }),
        ])
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        expect(revoked()).toEqual([])
    })

    test('switching sends every token only to the host of the account that owns it', async () => {
        const ada = await signIn(US, 'ada')
        const bob = await signIn(EU, 'bob')
        queryClient.setQueryData(['signals', EU, 2, 'inbox'], { results: ['bob-report'] })

        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'bob' })
        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        expect(queryClient.getQueryData(['signals', EU, 2, 'inbox'])).toBeUndefined()
        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'ada' })
        await useAuthStore.getState().switchAccount(bob, { from: 'settings' })
        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'bob' })

        const misdirected = server.sent.filter(({ url, credentials }) =>
            credentials.some((token) => ownerHostOf(token) !== new URL(url).origin)
        )
        expect(misdirected).toEqual([])
        expect(server.sent.length).toBeGreaterThan(4)
    })

    test('a switch reports under the account it leaves, then resets and identifies the next one', async () => {
        const ada = await signIn(US, 'ada')
        await signIn(EU, 'bob')
        const calls: string[] = []
        setAnalyticsClient({
            capture: (event: AnalyticsEvent, properties) => {
                if (event === 'mobile_account_switched') {
                    calls.push(`capture ${event} ${JSON.stringify(properties)}`)
                }
            },
            identify: (distinctId) => calls.push(`identify ${distinctId}`),
            reset: () => calls.push('reset'),
        })

        await useAuthStore.getState().switchAccount(ada, { from: 'nav_menu' })

        expect(calls).toEqual([
            'capture mobile_account_switched {"from":"nav_menu","account_count":2}',
            'reset',
            'identify ada-distinct',
        ])
    })

    test.each([
        { name: 'the user switched away', removeAccount: false },
        { name: 'the account was signed out', removeAccount: true },
    ])('a refresh that resolves after $name never reaches another account', async ({ removeAccount }) => {
        const ada = await signIn(US, 'ada')
        const bob = await signIn(EU, 'bob')
        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        const bobSlot = slot(bob)
        const held = holdNextRefresh()
        const refresh = refreshAccessToken()
        await held.reached

        await useAuthStore.getState().switchAccount(bob, { from: 'settings' })
        if (removeAccount) {
            await useAuthStore.getState().signOutAccount(ada)
        }
        held.release()

        await expect(refresh).resolves.toBeNull()
        const rotated = [...server.owners.keys()].filter((token) => token.startsWith('ada-refresh-')).at(-1) as string
        expect(getSessionTokens()?.accessToken).toBe(bobSlot?.tokens.accessToken)
        expect(slot(bob)).toEqual(bobSlot)
        expect(slot(ada)?.tokens.refreshToken ?? null).toBe(removeAccount ? null : rotated)
        expect(revoked().includes(rotated)).toBe(removeAccount)
        if (!removeAccount) {
            // The rotated pair works, so the account keeps its token family.
            await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
            await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'ada' })
        }
    })

    test.each([
        { name: 'refuses', unreachable: false, active: 'bob', needsSignIn: true },
        { name: 'cannot be reached', unreachable: true, active: 'ada', needsSignIn: false },
    ])('a switch whose token refresh the server $name', async ({ unreachable, active, needsSignIn }) => {
        server.expiresIn = 30
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken as string
        server.expiresIn = WEEK_S
        const bob = await signIn(EU, 'bob')
        const generation = sessionGeneration()
        server.refused.add(adaRefresh)
        server.unreachable = unreachable

        const switching = useAuthStore.getState().switchAccount(ada, { from: 'settings' })

        if (needsSignIn) {
            await expect(switching).rejects.toBeInstanceOf(AccountNeedsSignInError)
            expect(sessionGeneration()).toBe(generation)
            expect(slot(ada)).toBeNull()
            expect(removed).toEqual([{ key: ada, host: US, userUuid: 'ada' }])
        } else {
            await switching
            expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        }
        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            activeAccountKey: active === 'ada' ? ada : bob,
            user: { uuid: active },
        })
        expect(useAuthStore.getState().accounts.find((account) => account.key === ada)?.needsSignIn).toBe(needsSignIn)
    })

    test('adding an account that is already on the device revokes the new token and changes nothing', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')
        const generation = sessionGeneration()
        const before = useAuthStore.getState().accounts

        const adding = signIn(US, 'ada')

        await expect(adding).rejects.toBeInstanceOf(AccountAlreadyAddedError)
        await expect(adding).rejects.toMatchObject({ key: ada, email: 'ada@example.com', host: US })
        const duplicate = [...server.owners.keys()].filter((token) => token.startsWith('ada-refresh-')).at(-1)
        expect(revoked()).toEqual([duplicate])
        expect(duplicate).not.toBe(adaRefresh)
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        expect(sessionGeneration()).toBe(generation)
        expect(useAuthStore.getState()).toMatchObject({ activeAccountKey: bob, accounts: before })
    })

    test('signing out of the active account removes only it and switches to the other', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')
        const bobRefresh = getSessionTokens()?.refreshToken

        await useAuthStore.getState().signOut()

        expect(removed).toEqual([{ key: bob, host: EU, userUuid: 'bob' }])
        expect(revoked()).toEqual([bobRefresh])
        expect(slot(bob)).toBeNull()
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            activeAccountKey: ada,
            user: { uuid: 'ada' },
            accounts: [expect.objectContaining({ key: ada })],
        })
        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'ada' })
    })

    test('signing out of an inactive account leaves the session, its generation and its cache alone', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')
        const generation = sessionGeneration()
        const bobTokens = getSessionTokens()
        queryClient.setQueryData(['signals', EU, 2, 'inbox'], { results: ['bob-report'] })

        await useAuthStore.getState().signOutAccount(ada)

        expect(removed).toEqual([{ key: ada, host: US, userUuid: 'ada' }])
        expect(revoked()).toEqual([adaRefresh])
        expect(slot(ada)).toBeNull()
        expect(sessionGeneration()).toBe(generation)
        expect(getSessionTokens()).toBe(bobTokens)
        expect(queryClient.getQueryData(['signals', EU, 2, 'inbox'])).toEqual({ results: ['bob-report'] })
        expect(useAuthStore.getState()).toMatchObject({
            activeAccountKey: bob,
            accounts: [expect.objectContaining({ key: bob })],
        })
    })

    test('an expired active account keeps the other accounts and activates none of them', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')

        await expireActiveSession()

        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_out',
            signedOutReason: 'expired',
            activeAccountKey: null,
        })
        expect(useAuthStore.getState().accounts).toEqual([
            expect.objectContaining({ key: ada, needsSignIn: false }),
            expect.objectContaining({ key: bob, needsSignIn: true }),
        ])
        expect(removed).toEqual([{ key: bob, host: EU, userUuid: 'bob' }])
        expect(slot(bob)).toBeNull()
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)

        await useAuthStore.getState().switchAccount(ada, { from: 'sign_in' })
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: ada })
    })
})
