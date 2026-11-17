import * as SecureStore from 'expo-secure-store'
import { AppState } from 'react-native'
import { accountKey } from './accountKey'
import { installAuthProvider, refreshAccessToken, useAuthStore } from './authStore'
import { getSessionIdentity, loadTokens, saveTokens, setSessionTokens } from './tokens'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
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

const tokens = {
    kind: 'oauth' as const,
    accessToken: 'example-access',
    refreshToken: 'example-refresh',
    expiresAt: 0,
    grantedScopes: null,
    requestedScopes: null,
}
const host = 'https://current.example.com'

function json(body: unknown): Response {
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function envelope(owner: { host: string; userUuid: string }, accessToken: string): string {
    return JSON.stringify({
        version: 1,
        identity: { host: owner.host, clientId: 'example-client', method: 'oauth', userUuid: owner.userUuid },
        tokens: { ...tokens, accessToken },
    })
}

describe('stored session identity', () => {
    beforeEach(() => {
        mockSecureItems.clear()
    })

    test('rejects credentials without a stored destination', async () => {
        await SecureStore.setItemAsync('posthog_mobile_session', JSON.stringify(tokens))
        expect(await loadTokens()).toBeNull()
    })

    test('moves the session of the single-account app into its account slot', async () => {
        const owner = { host, userUuid: 'legacy-user' }
        await SecureStore.setItemAsync('posthog_mobile_session', envelope(owner, 'legacy-access'))

        expect(await loadTokens()).toMatchObject({ accessToken: 'legacy-access' })

        const key = await accountKey(host, 'legacy-user')
        expect(getSessionIdentity()).toMatchObject(owner)
        expect(await SecureStore.getItemAsync('posthog_mobile_session')).toBeNull()
        expect(JSON.parse((await SecureStore.getItemAsync('posthog_mobile_accounts')) ?? '{}')).toEqual({
            version: 1,
            active: key,
            keys: [key],
        })
        setSessionTokens(null)
        expect(await loadTokens()).toMatchObject({ accessToken: 'legacy-access' })
    })

    test('a slot that holds another account reads as absent and leaves the index', async () => {
        const key = await accountKey(host, 'slot-owner')
        await SecureStore.setItemAsync(
            `posthog_mobile_session.${key}`,
            envelope({ host: 'https://other.example.com', userUuid: 'slot-owner' }, 'misplaced-access')
        )
        await SecureStore.setItemAsync(
            'posthog_mobile_accounts',
            JSON.stringify({ version: 1, active: key, keys: [key] })
        )

        expect(await loadTokens()).toBeNull()

        expect(getSessionIdentity()).toBeNull()
        expect(await SecureStore.getItemAsync(`posthog_mobile_session.${key}`)).toBeNull()
        expect(JSON.parse((await SecureStore.getItemAsync('posthog_mobile_accounts')) ?? '{}')).toMatchObject({
            active: null,
            keys: [],
        })
    })

    test('restores a valid session before a stalled refresh and allows a later refresh to recover', async () => {
        jest.useFakeTimers()
        const previousState = AppState.currentState
        AppState.currentState = 'active'
        try {
            let stalledSignal: AbortSignal | null | undefined
            let stall = true
            const requests: string[] = []
            globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
                requests.push(url)
                if (url.endsWith('/oauth/token')) {
                    if (stall) {
                        stall = false
                        stalledSignal = init?.signal
                        return Object.assign(json({}), { json: () => new Promise<never>(() => undefined) })
                    }
                    return json({
                        access_token: 'example-rotated-access',
                        refresh_token: 'example-rotated-refresh',
                        expires_in: 3600,
                    })
                }
                return json({
                    id: 1,
                    uuid: 'current-user',
                    distinct_id: 'current-user',
                    email: 'current@example.com',
                    first_name: '',
                    last_name: '',
                    team: null,
                    organization: null,
                    organizations: [],
                })
            }) as unknown as typeof fetch
            await saveTokens(
                { ...tokens, expiresAt: Date.now() + 10 * 60_000 },
                { host, clientId: 'example-client', method: 'oauth', userUuid: 'current-user' }
            )
            useAuthStore.setState({
                status: 'loading',
                signedIn: false,
                host: 'https://previous.example.com',
                clientId: 'previous-client',
                method: 'oauth',
                user: {
                    uuid: 'previous-user',
                    distinctId: 'previous-user',
                    email: 'previous@example.com',
                    name: 'Previous',
                },
                projectId: 9,
                projects: [
                    {
                        id: 9,
                        name: 'Previous project',
                        organizationId: 'previous-org',
                        organizationName: 'Previous organization',
                    },
                ],
            })
            setSessionTokens(null)
            installAuthProvider()
            const restoring = useAuthStore.getState().restore()
            await jest.advanceTimersByTimeAsync(0)
            await restoring
            expect(useAuthStore.getState().status).toBe('signed_in')
            expect(stalledSignal?.aborted).toBe(false)
            await jest.advanceTimersByTimeAsync(20_000)
            expect(stalledSignal?.aborted).toBe(true)
            expect(useAuthStore.getState()).toMatchObject({ status: 'signed_in', signedIn: true })
            expect(await loadTokens()).toMatchObject({ accessToken: 'example-access', refreshToken: 'example-refresh' })
            expect(requests).toEqual([`${host}/api/users/@me/`, `${host}/oauth/token`])
            expect(useAuthStore.getState()).toMatchObject({
                host,
                clientId: 'example-client',
                user: { uuid: 'current-user' },
                projectId: null,
                projects: [],
            })
            await expect(refreshAccessToken()).resolves.toBe('example-rotated-access')
            expect(requests.filter((url) => url.endsWith('/oauth/token'))).toHaveLength(2)
            const slot = `posthog_mobile_session.${await accountKey(host, 'current-user')}`
            expect(JSON.parse((await SecureStore.getItemAsync(slot)) ?? '{}')).toMatchObject({
                identity: { host, userUuid: 'current-user' },
                tokens: { accessToken: 'example-rotated-access' },
            })
        } finally {
            AppState.currentState = previousState
            jest.useRealTimers()
        }
    })
})
