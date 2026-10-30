import * as SecureStore from 'expo-secure-store'
import { apiJson, NotSignedInError, projectPath } from '@/api/client'

import { addSessionEndTask, addSignOutTask, installAuthProvider, useAuthStore } from './authStore'
import { OAuthError } from './oauth'
import { getSessionIdentity, getSessionTokens, loadTokens, saveTokens, setSessionTokens } from './tokens'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))
jest.mock('expo-auth-session', () => ({
    AuthRequest: jest.fn().mockImplementation(() => ({
        redirectUri: 'posthog://callback',
        codeVerifier: 'fake-verifier',
        promptAsync: async () => ({ type: 'success', params: { code: 'fake-code' } }),
    })),
    makeRedirectUri: () => 'posthog://callback',
}))
jest.mock('expo-secure-store', () => {
    const items = new Map<string, string>()
    return {
        getItemAsync: async (key: string) => items.get(key) ?? null,
        setItemAsync: async (key: string, value: string) => {
            items.set(key, value)
        },
        deleteItemAsync: async (key: string) => {
            items.delete(key)
        },
    }
})

const HOST = 'https://us.posthog.com'
const OLD_HOST = 'https://old-instance.example.com'
const NEW_HOST = 'https://new-instance.example.com'

function accountResponse(uuid: string): Response {
    return json(200, {
        id: 7,
        uuid,
        distinct_id: uuid,
        email: `${uuid}@example.com`,
        first_name: '',
        last_name: '',
        team: null,
        organization: null,
        organizations: [],
    })
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function authorization(init: RequestInit | undefined): string | undefined {
    return (init?.headers as Record<string, string> | undefined)?.Authorization
}

describe('token refresh through the API client', () => {
    const fetchMock = jest.fn<Promise<Response>, [string, RequestInit | undefined]>()

    beforeEach(async () => {
        globalThis.fetch = fetchMock as unknown as typeof fetch
        fetchMock.mockReset()
        installAuthProvider()
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: HOST,
            clientId: 'test-client',
            projectId: 2,
            signedOutReason: null,
        })
        await saveTokens(
            {
                kind: 'oauth',
                accessToken: 'old-access',
                refreshToken: 'old-refresh',
                expiresAt: Date.now() + 60_000,
                grantedScopes: ['user:read', 'dashboard:read'],
                requestedScopes: ['user:read', 'dashboard:read', 'insight:read'],
            },
            { host: HOST, clientId: 'test-client', method: 'oauth', userUuid: 'example-user' }
        )
    })

    test('concurrent 401s share one refresh, store the rotated pair and retry with the new token', async () => {
        const tokenBodies: unknown[] = []
        fetchMock.mockImplementation(async (url, init) => {
            if (url === `${HOST}/oauth/token`) {
                tokenBodies.push(JSON.parse(String(init?.body)))
                // Answer on a later task, so both 401 handlers are already waiting on this refresh.
                await new Promise((resolve) => setTimeout(resolve, 0))
                return json(200, { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 604800 })
            }
            return authorization(init) === 'Bearer new-access' ? json(200, { url }) : json(401, { detail: 'expired' })
        })

        const results = await Promise.all([
            apiJson<{ url: string }>('/api/users/@me/'),
            apiJson<{ url: string }>(projectPath('signals/reports/')),
        ])

        expect(results).toEqual([{ url: `${HOST}/api/users/@me/` }, { url: `${HOST}/api/projects/2/signals/reports/` }])
        expect(tokenBodies).toEqual([
            { grant_type: 'refresh_token', refresh_token: 'old-refresh', client_id: 'test-client' },
        ])
        setSessionTokens(null)
        expect(await loadTokens()).toMatchObject({
            accessToken: 'new-access',
            refreshToken: 'new-refresh',
            grantedScopes: ['user:read', 'dashboard:read'],
            requestedScopes: ['user:read', 'dashboard:read', 'insight:read'],
        })
        expect(useAuthStore.getState().status).toBe('signed_in')
    })

    test.each([
        {
            name: 'a rejected refresh token signs the user out',
            token: async (): Promise<Response> => json(400, { error: 'invalid_grant' }),
            error: NotSignedInError,
            status: 'signed_out',
            reason: 'expired',
            accessToken: undefined,
        },
        {
            name: 'a network failure keeps the session for a later retry',
            token: async (): Promise<Response> => {
                throw new TypeError('Network request failed')
            },
            error: OAuthError,
            status: 'signed_in',
            reason: null,
            accessToken: 'old-access',
        },
    ])('$name', async ({ token, error, status, reason, accessToken }) => {
        fetchMock.mockImplementation(async (url) => (url === `${HOST}/oauth/token` ? token() : json(401, {})))

        await expect(apiJson('/api/users/@me/')).rejects.toBeInstanceOf(error)

        expect(useAuthStore.getState()).toMatchObject({ status, signedOutReason: reason })
        expect(getSessionTokens()?.accessToken).toBe(accessToken)
    })

    test.each([
        { name: 'API response', held: `${OLD_HOST}/api/users/@me/`, answer: (): Response => json(401, {}) },
        {
            name: 'token refresh',
            held: `${OLD_HOST}/oauth/token`,
            answer: (): Response =>
                json(200, { access_token: 'rotated-access', refresh_token: 'rotated-refresh', expires_in: 3600 }),
        },
    ])('an old host $name held across signing in elsewhere never gets the new session', async ({ held, answer }) => {
        const sent: { url: string; credentials: string }[] = []
        let release: (response: Response) => void = () => undefined
        let reached: () => void = () => undefined
        const heldReached = new Promise<void>((resolve) => {
            reached = resolve
        })
        let holding = true
        fetchMock.mockImplementation(async (url, init) => {
            sent.push({ url, credentials: `${authorization(init)} ${String(init?.body)}` })
            if (url === held && holding) {
                holding = false
                reached()
                return new Promise<Response>((resolve) => {
                    release = resolve
                })
            }
            if (url === `${OLD_HOST}/api/users/@me/`) {
                return json(401, {})
            }
            if (url === `${OLD_HOST}/oauth/revoke`) {
                return json(200, {})
            }
            if (url === `${HOST}/oauth/token`) {
                return json(200, { access_token: 'next-access', refresh_token: 'next-refresh', expires_in: 3600 })
            }
            if (url === `${HOST}/api/users/@me/` && authorization(init) === 'Bearer next-access') {
                return json(200, {
                    id: 7,
                    uuid: 'next-user',
                    distinct_id: 'next-user',
                    email: 'next-user@example.com',
                    first_name: '',
                    last_name: '',
                    team: null,
                    organization: null,
                    organizations: [],
                })
            }
            throw new Error(`Unexpected request to ${url}`)
        })
        useAuthStore.setState({ host: OLD_HOST, clientId: 'old-client', method: 'oauth' })

        const reload = useAuthStore.getState().reloadAccount()
        await heldReached
        await useAuthStore.getState().signOut()
        await useAuthStore.getState().signIn(HOST, 'next-client')
        release(answer())
        await reload

        expect(
            sent.filter(({ url, credentials }) => url.startsWith(OLD_HOST) && credentials.includes('next-'))
        ).toEqual([])
        expect(await apiJson('/api/users/@me/')).toMatchObject({ uuid: 'next-user' })
        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            host: HOST,
            user: { uuid: 'next-user' },
            accountError: null,
        })
        expect(getSessionTokens()).toMatchObject({ accessToken: 'next-access', refreshToken: 'next-refresh' })
    })

    test('a candidate host and token stay separate until its account is loaded', async () => {
        let releaseMe: (response: Response) => void = () => undefined
        let reachedMe: () => void = () => undefined
        const meStarted = new Promise<void>((resolve) => {
            reachedMe = resolve
        })
        fetchMock.mockImplementation(async (url) => {
            if (url === `${NEW_HOST}/oauth/token`) {
                return json(200, { access_token: 'candidate', refresh_token: 'candidate-refresh', expires_in: 3600 })
            }
            if (url === `${NEW_HOST}/api/users/@me/`) {
                reachedMe()
                return new Promise<Response>((resolve) => {
                    releaseMe = resolve
                })
            }
            if (url === `${HOST}/oauth/revoke`) {
                return json(200, {})
            }
            throw new Error(`Unexpected request to ${url}`)
        })

        const signingIn = useAuthStore.getState().signIn(NEW_HOST, 'candidate-client')
        await meStarted
        expect(useAuthStore.getState().host).toBe(HOST)
        expect(getSessionTokens()?.accessToken).toBe('old-access')
        releaseMe(accountResponse('candidate-user'))
        await signingIn
        expect(useAuthStore.getState()).toMatchObject({ host: NEW_HOST, user: { uuid: 'candidate-user' } })
        expect(getSessionTokens()?.accessToken).toBe('candidate')
    })

    test('a failed candidate or canceled sign-in leaves the active host and credentials intact', async () => {
        const { AuthRequest } = jest.requireMock('expo-auth-session') as { AuthRequest: jest.Mock }
        AuthRequest.mockImplementationOnce(() => ({
            promptAsync: async () => ({ type: 'cancel' }),
        }))
        await expect(useAuthStore.getState().signIn(NEW_HOST, 'candidate-client')).rejects.toBeInstanceOf(OAuthError)

        fetchMock.mockImplementation(async (url) => {
            if (url === `${NEW_HOST}/api/users/@me/`) {
                return json(403, { detail: 'Account unavailable' })
            }
            throw new Error(`Unexpected request to ${url}`)
        })
        await expect(useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'candidate-key')).rejects.toThrow()
        expect(useAuthStore.getState().host).toBe(HOST)
        expect(getSessionTokens()?.accessToken).toBe('old-access')
    })

    test('failed session cleanup keeps the old credentials and a retry can sign out', async () => {
        const cleanup = jest.fn().mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(undefined)
        const removeCleanup = addSignOutTask(cleanup)
        fetchMock.mockResolvedValue(json(200, {}))
        try {
            await expect(useAuthStore.getState().signOut()).rejects.toThrow('Offline')
            expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', host: HOST })
            expect(getSessionTokens()?.accessToken).toBe('old-access')
            await useAuthStore.getState().signOut()
            expect(cleanup).toHaveBeenCalledTimes(2)
            expect(useAuthStore.getState().status).toBe('signed_out')
        } finally {
            removeCleanup()
        }
    })

    test('a failed account switch commit reopens the old session cleanup', async () => {
        const recover = jest.fn()
        const cleanup = jest.fn().mockResolvedValue(recover)
        const removeCleanup = addSignOutTask(cleanup)
        fetchMock.mockImplementation(async (url) => {
            if (url === `${NEW_HOST}/api/users/@me/`) {
                return accountResponse('candidate-user')
            }
            return json(200, {})
        })
        const storeWrite = jest
            .spyOn(SecureStore, 'setItemAsync')
            .mockRejectedValueOnce(new Error('Storage unavailable'))
        try {
            await expect(useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'candidate-key')).rejects.toThrow(
                'Storage unavailable'
            )
            expect(cleanup).toHaveBeenCalledTimes(1)
            expect(recover).toHaveBeenCalledTimes(1)
            expect(useAuthStore.getState().host).toBe(HOST)
            expect(getSessionTokens()?.accessToken).toBe('old-access')
        } finally {
            storeWrite.mockRestore()
            removeCleanup()
        }
    })

    test('a later concurrent sign-in wins without publishing the first candidate', async () => {
        let releaseFirst: (response: Response) => void = () => undefined
        let firstStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            firstStarted = resolve
        })
        fetchMock.mockImplementation(async (url, init) => {
            if (url === `${NEW_HOST}/api/users/@me/`) {
                if (authorization(init) === 'Bearer first-key') {
                    firstStarted()
                    return new Promise<Response>((resolve) => {
                        releaseFirst = resolve
                    })
                }
                return accountResponse('second-user')
            }
            throw new Error(`Unexpected request to ${url}`)
        })
        const first = useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'first-key')
        await started
        await useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'second-key')
        releaseFirst(accountResponse('first-user'))
        await expect(first).rejects.toBeInstanceOf(OAuthError)
        expect(useAuthStore.getState().user?.uuid).toBe('second-user')
        expect(getSessionTokens()?.accessToken).toBe('second-key')
    })

    test('account switch finishes old session cleanup before publishing the new account', async () => {
        let finishCleanup: () => void = () => undefined
        let cleanupStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            cleanupStarted = resolve
        })
        const removeCleanup = addSessionEndTask(
            () =>
                new Promise<void>((resolve) => {
                    cleanupStarted()
                    finishCleanup = resolve
                })
        )
        fetchMock.mockImplementation(async (url) => {
            if (url === `${NEW_HOST}/api/users/@me/`) {
                return accountResponse('candidate-user')
            }
            return json(200, {})
        })
        try {
            const signingIn = useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'candidate-key')
            await started
            expect(useAuthStore.getState().host).toBe(HOST)
            expect(getSessionTokens()?.accessToken).toBe('old-access')
            finishCleanup()
            await signingIn
            expect(useAuthStore.getState().host).toBe(NEW_HOST)
        } finally {
            removeCleanup()
        }
    })

    test('a candidate canceled during SecureStore write never replaces the later sign-in', async () => {
        fetchMock.mockImplementation(async (url, init) => {
            if (url === `${NEW_HOST}/api/users/@me/`) {
                return accountResponse(authorization(init) === 'Bearer first-key' ? 'first-user' : 'second-user')
            }
            throw new Error(`Unexpected request to ${url}`)
        })
        const originalWrite = SecureStore.setItemAsync
        let finishWrite: () => void = () => undefined
        let writeStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            writeStarted = resolve
        })
        const storeWrite = jest.spyOn(SecureStore, 'setItemAsync').mockImplementationOnce(
            (key, value) =>
                new Promise<void>((resolve) => {
                    writeStarted()
                    finishWrite = () => void originalWrite(key, value).then(resolve)
                })
        )
        try {
            const first = useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'first-key')
            await started
            const second = useAuthStore.getState().signInWithPersonalApiKey(NEW_HOST, 'second-key')
            finishWrite()
            await expect(first).rejects.toBeInstanceOf(OAuthError)
            await second
            expect(useAuthStore.getState().user?.uuid).toBe('second-user')
            setSessionTokens(null)
            expect((await loadTokens())?.accessToken).toBe('second-key')
            expect(getSessionIdentity()).toMatchObject({
                host: NEW_HOST,
                userUuid: 'second-user',
                method: 'personal_api_key',
            })
        } finally {
            storeWrite.mockRestore()
        }
    })

    test('two sign-out requests share one cleanup and leave one signed-out session', async () => {
        let finishCleanup: () => void = () => undefined
        let cleanupStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            cleanupStarted = resolve
        })
        const cleanup = jest.fn().mockImplementation(
            () =>
                new Promise<void>((resolve) => {
                    cleanupStarted()
                    finishCleanup = resolve
                })
        )
        const removeCleanup = addSignOutTask(cleanup)
        fetchMock.mockResolvedValue(json(200, {}))
        try {
            const first = useAuthStore.getState().signOut()
            const second = useAuthStore.getState().signOut()
            await started
            expect(cleanup).toHaveBeenCalledTimes(1)
            finishCleanup()
            await Promise.all([first, second])
            expect(cleanup).toHaveBeenCalledTimes(1)
            expect(useAuthStore.getState().status).toBe('signed_out')
        } finally {
            removeCleanup()
        }
    })
})
