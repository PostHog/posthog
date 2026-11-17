import * as SecureStore from 'expo-secure-store'

import { apiJson, apiStream, NotSignedInError, SessionEndedError } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { type AnalyticsEvent, setAnalyticsClient, track } from '@/lib/analytics'

import type { AccountRef } from './accountKey'
import { accountKey } from './accountKey'
import {
    AccountAlreadyAddedError,
    AccountNeedsSignInError,
    addAccountRemovedTask,
    addAccountSwitchTask,
    addSwitchRollbackTask,
    installAuthProvider,
    refreshAccessToken,
    useAuthStore,
} from './authStore'
import {
    getSessionTokens,
    onSessionTokensChanged,
    readAccountSession,
    sessionGeneration,
    setSessionTokens,
} from './tokens'

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
/** Items whose read throws, as a keychain does before the first unlock. */
const mockUnreadable = new Set<string>()
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

const US = 'https://us.posthog.com'
const EU = 'https://eu.posthog.com'
const CLIENT = 'example-client'
// First-party access tokens last a week, so a switch starts no foreground refresh on its own.
const WEEK_S = 7 * 24 * 3600
const REUSE_WINDOW_MS = 2 * 60_000
const ISSUE_PATH = '/api/projects/2/error_tracking/issues/issue-1/'

interface Sent {
    url: string
    /** Every credential the request carried: its bearer token and any token in its body. */
    credentials: string[]
}

interface Hold {
    reached: () => void
    response: Promise<Response>
}

/**
 * A PostHog instance per host that rotates refresh tokens and knows which user owns each token. A rotated refresh
 * token replayed within two minutes gets the same pair again. A later replay revokes the whole token family.
 */
const server = {
    browserUser: 'ada',
    expiresIn: WEEK_S,
    unreachable: false,
    owners: new Map<string, { host: string; user: string; family: string }>(),
    refused: new Set<string>(),
    rotations: new Map<string, { at: number; access: string; refresh: string }>(),
    revokedFamilies: new Set<string>(),
    replayed: [] as string[],
    sent: [] as Sent[],
    issued: 0,
    heldRefresh: null as null | { reached: () => void; release: Promise<void> },
    holds: new Map<string, Hold>(),
    onRevoke: null as null | ((token: string) => Promise<void>),
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function issue(
    host: string,
    user: string,
    family = `family-${server.issued + 1}`
): { access: string; refresh: string } {
    server.issued += 1
    const access = `${user}-access-${server.issued}`
    const refresh = `${user}-refresh-${server.issued}`
    server.owners.set(access, { host, user, family })
    server.owners.set(refresh, { host, user, family })
    return { access, refresh }
}

function tokenResponse({ access, refresh }: { access: string; refresh: string }): Response {
    return json(200, { access_token: access, refresh_token: refresh, expires_in: server.expiresIn })
}

function live(token: string | undefined, origin: string): { host: string; user: string } | null {
    const owner = token ? server.owners.get(token) : undefined
    if (
        !owner ||
        owner.host !== origin ||
        server.refused.has(token as string) ||
        server.revokedFamilies.has(owner.family)
    ) {
        return null
    }
    return owner
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
        return tokenResponse(issue(origin, server.browserUser))
    }
    if (pathname === '/oauth/token') {
        const owner = live(fields.refresh_token, origin)
        if (!owner) {
            return json(400, { error: 'invalid_grant' })
        }
        const rotation = server.rotations.get(fields.refresh_token)
        if (rotation) {
            server.replayed.push(fields.refresh_token)
            if (Date.now() - rotation.at > REUSE_WINDOW_MS) {
                server.revokedFamilies.add(server.owners.get(fields.refresh_token)?.family as string)
                return json(400, { error: 'invalid_grant' })
            }
            return tokenResponse(rotation)
        }
        const pair = issue(origin, owner.user, server.owners.get(fields.refresh_token)?.family)
        server.rotations.set(fields.refresh_token, { at: Date.now(), ...pair })
        const rotated = tokenResponse(pair)
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
        await server.onRevoke?.(fields.token)
        return json(200, {})
    }
    const owner = live(bearer, origin)
    if (!owner) {
        return json(401, { detail: 'expired' })
    }
    if (pathname === '/api/users/@me/') {
        return json(200, {
            id: 7,
            uuid: owner.user,
            distinct_id: `${owner.user}-distinct`,
            email: `${owner.user}@example.com`,
            first_name: '',
            last_name: '',
            team: { id: 2 },
            organization: { id: `${owner.user}-org`, name: 'Example org', teams: [{ id: 2, name: 'Web' }] },
            organizations: [{ id: `${owner.user}-org`, name: 'Example org' }],
        })
    }
    const hold = server.holds.get(pathname)
    if (hold) {
        server.holds.delete(pathname)
        hold.reached()
        return hold.response
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

/** Holds the next request to `pathname` until `release` answers it. */
function holdRequest(pathname: string): { reached: Promise<void>; release: (response: Response) => void } {
    let release: (response: Response) => void = () => undefined
    let reached: () => void = () => undefined
    const reachedPromise = new Promise<void>((resolve) => {
        reached = resolve
    })
    server.holds.set(pathname, {
        reached,
        response: new Promise<Response>((resolve) => {
            release = resolve
        }),
    })
    return { reached: reachedPromise, release: (response) => release(response) }
}

async function signIn(host: string, user: string, options?: { reauth?: string }): Promise<string> {
    server.browserUser = user
    await useAuthStore.getState().signIn(host, CLIENT, options)
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

function lastIssued(prefix: string): string {
    return [...server.owners.keys()].filter((token) => token.startsWith(prefix)).at(-1) as string
}

function recordAnalytics(): string[] {
    const calls: string[] = []
    setAnalyticsClient({
        capture: (event: AnalyticsEvent, properties) =>
            calls.push(properties ? `capture ${event} ${JSON.stringify(properties)}` : `capture ${event}`),
        identify: (distinctId) => calls.push(`identify ${distinctId}`),
        reset: () => calls.push('reset'),
    })
    return calls
}

async function tick(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 10))
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
        ;(jest.requireMock('expo/fetch') as { fetch: jest.Mock }).fetch.mockImplementation(answer)
        mockSecureItems.clear()
        mockUnreadable.clear()
        mockPromptOptions.length = 0
        removed.length = 0
        Object.assign(server, {
            browserUser: 'ada',
            expiresIn: WEEK_S,
            unreachable: false,
            heldRefresh: null,
            onRevoke: null,
            sent: [],
            replayed: [],
        })
        server.owners.clear()
        server.refused.clear()
        server.rotations.clear()
        server.revokedFamilies.clear()
        server.holds.clear()
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
            unreadableAccountKeys: [],
            pendingSlotRemovals: [],
            freshLoginNext: false,
            signedOutReason: null,
            expiredAccountKey: null,
        })
        installAuthProvider()
    })

    afterEach(() => {
        setAnalyticsClient(null)
        jest.useRealTimers()
    })

    async function expireActiveSession(): Promise<void> {
        server.refused.add(getSessionTokens()?.accessToken as string)
        server.refused.add(getSessionTokens()?.refreshToken as string)
        await expect(apiJson('/api/users/@me/')).rejects.toBeInstanceOf(NotSignedInError)
        // The request ends before the session-end tasks, so its own continuation runs under the account it belonged to.
        for (let ticks = 0; useAuthStore.getState().status !== 'signed_out'; ticks += 1) {
            if (ticks > 100) {
                throw new Error('The expired session did not end')
            }
            await tick()
        }
    }

    test.each([
        {
            name: 'with no account and no sign-out',
            before: async (): Promise<void> => undefined,
            options: undefined,
            ephemeral: false,
        },
        {
            name: 'while another account is signed in',
            before: async (): Promise<void> => {
                await signIn(EU, 'bob')
            },
            options: undefined,
            ephemeral: true,
        },
        {
            name: 'when the user asks for a different account',
            before: async (): Promise<void> => undefined,
            options: { freshLogin: true },
            ephemeral: true,
        },
        {
            name: 'after the user signed out',
            before: async (): Promise<void> => {
                await signIn(US, 'ada')
                await useAuthStore.getState().signOut()
            },
            options: undefined,
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
            options: undefined,
            ephemeral: false,
        },
        {
            name: 'that signs the only account in again',
            before: async (): Promise<void> => {
                await signIn(US, 'ada')
            },
            options: { reauth: Buffer.from(JSON.stringify([US, 'ada'])).toString('hex') },
            ephemeral: false,
        },
    ])('a sign-in $name keeps the browser session out: $ephemeral', async ({ before, options, ephemeral }) => {
        await before()
        mockPromptOptions.length = 0
        server.browserUser = 'ada'

        await useAuthStore.getState().signIn(US, CLIENT, options)

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

    test('no request gets the token while the session fields show another host', async () => {
        await signIn(EU, 'bob')
        const sent = server.sent.length
        useAuthStore.setState({ host: US })

        await expect(apiJson('/api/users/@me/')).rejects.toBeInstanceOf(NotSignedInError)

        expect(server.sent.slice(sent)).toEqual([])
    })

    test('every event around a switch: the leaving user, a reset before activation, then the next user', async () => {
        const ada = await signIn(US, 'ada')
        await signIn(EU, 'bob')
        const calls = recordAnalytics()
        // Token listeners run during activation, as the home screen widget's sync does.
        const stopListener = onSessionTokensChanged((change) => {
            if (change === 'session') {
                track('mobile_widget_credentials_synced', { reason: 'sign_in' })
            }
        })

        try {
            await useAuthStore.getState().switchAccount(ada, { from: 'nav_menu' })
        } finally {
            stopListener()
        }

        expect(calls).toEqual([
            'capture mobile_account_switched {"from":"nav_menu","account_count":2}',
            'reset',
            'capture mobile_widget_credentials_synced {"reason":"sign_in"}',
            'identify ada-distinct',
        ])
    })

    test('a switch that fails to activate gives the session, its analytics, push and refreshed token back', async () => {
        jest.useFakeTimers({ advanceTimers: true })
        const ada = await signIn(US, 'ada')
        const bob = await signIn(EU, 'bob')
        const bobRefresh = getSessionTokens()?.refreshToken as string
        const calls = recordAnalytics()
        const rolledBack: AccountRef[] = []
        const stopRollback = addSwitchRollbackTask((account) => {
            rolledBack.push(account)
        })
        const held = holdNextRefresh()
        const refresh = refreshAccessToken()
        await held.reached
        const write = jest.spyOn(SecureStore, 'setItemAsync').mockImplementationOnce(async (key) => {
            throw new Error(`Storage unavailable for ${key}`)
        })

        try {
            await expect(useAuthStore.getState().switchAccount(ada, { from: 'settings' })).rejects.toThrow(
                'Storage unavailable for posthog_mobile_accounts'
            )
            held.release()
            await expect(refresh).resolves.toBeNull()
        } finally {
            write.mockRestore()
            stopRollback()
        }

        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: bob })
        expect(calls).toEqual([
            'capture mobile_account_switched {"from":"settings","account_count":2}',
            'reset',
            'identify bob-distinct',
        ])
        expect(rolledBack).toEqual([{ key: bob, host: EU, userUuid: 'bob' }])
        // The server consumed the refresh token, so memory must hold the rotated pair that the slot holds.
        const rotated = server.rotations.get(bobRefresh)?.refresh
        expect(getSessionTokens()?.refreshToken).toBe(rotated)
        expect(slot(bob)?.tokens.refreshToken).toBe(rotated)
        jest.setSystemTime(Date.now() + 2 * REUSE_WINDOW_MS)
        server.refused.add(getSessionTokens()?.accessToken as string)
        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'bob' })
        expect(server.replayed).toEqual([])
    })

    test('a switch back to an account waits for its refresh, so the switch never replays a consumed token', async () => {
        jest.useFakeTimers({ advanceTimers: true })
        const bob = await signIn(EU, 'bob')
        server.expiresIn = 30
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken as string
        server.expiresIn = WEEK_S
        const bobSlot = slot(bob)
        const held = holdNextRefresh()
        const refresh = refreshAccessToken()
        await held.reached
        await useAuthStore.getState().switchAccount(bob, { from: 'settings' })
        jest.setSystemTime(Date.now() + 2 * REUSE_WINDOW_MS)

        const switching = useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        await tick()
        held.release()

        await expect(switching).resolves.toBeUndefined()
        await expect(refresh).resolves.toBeNull()
        const rotated = server.rotations.get(adaRefresh)?.refresh
        expect(server.replayed).toEqual([])
        expect(slot(bob)).toEqual(bobSlot)
        expect(slot(ada)?.tokens.refreshToken).toBe(rotated)
        expect(getSessionTokens()?.refreshToken).toBe(rotated)
        await expect(apiJson('/api/users/@me/')).resolves.toMatchObject({ uuid: 'ada' })
    })

    test.each([
        { name: 'the active account', active: true },
        { name: 'an inactive account', active: false },
    ])('signing out of $name waits for its refresh and revokes the rotated token', async ({ active }) => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken as string
        const bob = await signIn(EU, 'bob')
        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        const held = holdNextRefresh()
        const refresh = refreshAccessToken()
        await held.reached
        if (!active) {
            await useAuthStore.getState().switchAccount(bob, { from: 'settings' })
        }
        const rotated = server.rotations.get(adaRefresh)?.refresh as string
        // A sign out that revokes before the refresh lands: the rotated pair reaches the slot before the slot is deleted.
        server.onRevoke = async () => {
            held.release()
            for (let ticks = 0; slot(ada)?.tokens.refreshToken !== rotated && ticks < 50; ticks += 1) {
                await tick()
            }
        }

        const signingOut = useAuthStore.getState().signOutAccount(ada)
        await tick()
        held.release()
        await signingOut
        await refresh

        expect(revoked()).toContain(rotated)
        expect(slot(ada)).toBeNull()
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: bob })
    })

    test('a refresh whose slot cannot be read keeps the rotated pair for the slot and never revokes it', async () => {
        server.expiresIn = 30
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken as string
        server.expiresIn = WEEK_S
        await signIn(EU, 'bob')
        const held = holdNextRefresh()

        const switching = useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        await held.reached
        mockUnreadable.add(`posthog_mobile_session.${ada}`)
        held.release()
        await switching

        const rotated = server.rotations.get(adaRefresh)?.refresh as string
        expect(revoked()).not.toContain(rotated)
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: ada })
        expect(useAuthStore.getState().accounts.find((account) => account.key === ada)?.needsSignIn).toBe(false)
        expect(getSessionTokens()?.refreshToken).toBe(rotated)
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        mockUnreadable.clear()
        await expect(readAccountSession(ada)).resolves.toMatchObject({ session: { tokens: { refreshToken: rotated } } })
        expect(slot(ada)?.tokens.refreshToken).toBe(rotated)
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

    test('a switch to an account whose slot cannot be read fails and keeps the account', async () => {
        const ada = await signIn(US, 'ada')
        const bob = await signIn(EU, 'bob')
        const adaSlot = slot(ada)
        mockUnreadable.add(`posthog_mobile_session.${ada}`)

        await expect(useAuthStore.getState().switchAccount(ada, { from: 'settings' })).rejects.toThrow(
            "Couldn't read the sign-in for ada@example.com on this phone."
        )

        expect(useAuthStore.getState()).toMatchObject({ activeAccountKey: bob, unreadableAccountKeys: [ada] })
        expect(useAuthStore.getState().accounts.find((account) => account.key === ada)?.needsSignIn).toBe(false)
        expect(slot(ada)).toEqual(adaSlot)
        expect(removed).toEqual([])
        mockUnreadable.clear()
        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        expect(useAuthStore.getState()).toMatchObject({ activeAccountKey: ada, unreadableAccountKeys: [] })
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
        const duplicate = lastIssued('ada-refresh-')
        expect(revoked()).toEqual([duplicate])
        expect(duplicate).not.toBe(adaRefresh)
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)
        expect(sessionGeneration()).toBe(generation)
        expect(useAuthStore.getState()).toMatchObject({ activeAccountKey: bob, accounts: before })
    })

    test('while signed out, a sign-in to an account that is on the device replaces its slot and activates it', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken as string
        await signIn(EU, 'bob')
        await expireActiveSession()

        await signIn(US, 'ada')

        const fresh = lastIssued('ada-refresh-')
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: ada })
        expect(slot(ada)?.tokens.refreshToken).toBe(fresh)
        expect(revoked()).toContain(adaRefresh)
        expect(revoked()).not.toContain(fresh)
    })

    test('signing the active account in again keeps it active and leaves the other accounts alone', async () => {
        const ada = await signIn(US, 'ada')
        const adaSlot = slot(ada)
        const bob = await signIn(EU, 'bob')
        const bobRefresh = getSessionTokens()?.refreshToken as string
        const generation = sessionGeneration()
        const switched: AccountRef[] = []
        const stopSwitch = addAccountSwitchTask((next) => {
            switched.push(next)
        })

        try {
            await signIn(EU, 'bob', { reauth: bob })
        } finally {
            stopSwitch()
        }

        const fresh = lastIssued('bob-refresh-')
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: bob })
        expect(sessionGeneration()).not.toBe(generation)
        expect(getSessionTokens()?.refreshToken).toBe(fresh)
        expect(slot(bob)?.tokens.refreshToken).toBe(fresh)
        expect(revoked()).toEqual([bobRefresh])
        expect(slot(ada)).toEqual(adaSlot)
        expect(switched).toEqual([])
        expect(removed).toEqual([])
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

    test('a sign out whose slot delete fails records the removal for the next launch', async () => {
        const ada = await signIn(US, 'ada')
        await signIn(EU, 'bob')
        const remove = jest
            .spyOn(SecureStore, 'deleteItemAsync')
            .mockRejectedValueOnce(new Error('Storage unavailable'))

        try {
            await useAuthStore.getState().signOutAccount(ada)
        } finally {
            remove.mockRestore()
        }

        expect(useAuthStore.getState().pendingSlotRemovals).toEqual([ada])
        expect(useAuthStore.getState().accounts.some((account) => account.key === ada)).toBe(false)
    })

    test('an expired active account keeps only its name, activates no other account, and its sign out clears the notice', async () => {
        const ada = await signIn(US, 'ada')
        const adaRefresh = getSessionTokens()?.refreshToken
        const bob = await signIn(EU, 'bob')

        await expireActiveSession()

        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_out',
            signedOutReason: 'expired',
            expiredAccountKey: bob,
            activeAccountKey: null,
        })
        expect(useAuthStore.getState().accounts).toEqual([
            expect.objectContaining({ key: ada, needsSignIn: false, projects: [expect.objectContaining({ id: 2 })] }),
            {
                key: bob,
                host: EU,
                clientId: CLIENT,
                method: 'oauth',
                region: 'eu',
                userUuid: 'bob',
                user: { uuid: 'bob', distinctId: 'bob-distinct', email: 'bob@example.com', name: 'bob@example.com' },
                organizations: [],
                projects: [],
                projectId: null,
                needsSignIn: true,
                lastUsedAt: expect.any(Number),
            },
        ])
        expect(removed).toEqual([{ key: bob, host: EU, userUuid: 'bob' }])
        expect(slot(bob)).toBeNull()
        expect(slot(ada)?.tokens.refreshToken).toBe(adaRefresh)

        await useAuthStore.getState().signOutAccount(bob)
        expect(useAuthStore.getState()).toMatchObject({ signedOutReason: null, expiredAccountKey: null })
        await useAuthStore.getState().switchAccount(ada, { from: 'sign_in' })
        expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', activeAccountKey: ada })
    })

    test.each([
        { name: 'its response', status: 200 },
        { name: 'its failure', status: 500 },
    ])('$name after a switch writes nothing into the next session', async ({ status }) => {
        const ada = await signIn(US, 'ada')
        await signIn(US, 'bob')
        const key = ['issue', US, 2, 'issue-1']
        queryClient.setQueryData(key, { owner: 'bob', status: 'active' })
        const calls = recordAnalytics()
        const held = holdRequest(ISSUE_PATH)
        const settled = (async (): Promise<void> => {
            const previous = queryClient.getQueryData(key)
            queryClient.setQueryData(key, { owner: 'bob', status: 'resolved' })
            try {
                queryClient.setQueryData(key, await apiJson(ISSUE_PATH, { method: 'PATCH' }))
                track('mobile_issue_status_changed', { to: 'resolved' })
            } catch {
                queryClient.setQueryData(key, previous)
                track('mobile_handoff_failed', { reason: 'unknown' })
            }
        })()
        await held.reached

        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })
        held.release(json(status, { owner: 'bob', status: 'resolved' }))
        await settled

        expect(queryClient.getQueryData(key)).toBeUndefined()
        expect(calls.slice(calls.indexOf('reset'))).toEqual(['reset', 'identify ada-distinct'])
    })

    test('a stream of the earlier session ends at the switch', async () => {
        const ada = await signIn(US, 'ada')
        await signIn(EU, 'bob')
        holdRequest('/api/projects/2/conversations/')
        const stream = apiStream('/api/projects/2/conversations/', { method: 'POST' })
        let outcome: unknown = null
        stream.then(
            () => {
                outcome = 'open'
            },
            (error: unknown) => {
                outcome = error
            }
        )

        await useAuthStore.getState().switchAccount(ada, { from: 'settings' })

        expect(outcome).toBeInstanceOf(SessionEndedError)
    })
})
