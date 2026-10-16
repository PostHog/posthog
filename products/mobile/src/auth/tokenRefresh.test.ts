import { apiJson, NotSignedInError, projectPath } from '@/api/client'

import { installAuthProvider, useAuthStore } from './authStore'
import { OAuthError } from './oauth'
import { getSessionTokens, loadTokens, saveTokens, setSessionTokens } from './tokens'

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
        await saveTokens({
            kind: 'oauth',
            accessToken: 'old-access',
            refreshToken: 'old-refresh',
            expiresAt: Date.now() + 60_000,
            grantedScopes: ['user:read', 'dashboard:read'],
            requestedScopes: ['user:read', 'dashboard:read', 'insight:read'],
        })
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
})
