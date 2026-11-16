import * as SecureStore from 'expo-secure-store'
import { AppState } from 'react-native'
import { installAuthProvider, refreshAccessToken, useAuthStore } from './authStore'
import { loadTokens, saveTokens, setSessionTokens } from './tokens'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
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

describe('stored session identity', () => {
    test('rejects credentials without a stored destination', async () => {
        await SecureStore.setItemAsync('posthog_mobile_session', JSON.stringify(tokens))
        expect(await loadTokens()).toBeNull()
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
            expect(JSON.parse((await SecureStore.getItemAsync('posthog_mobile_session')) ?? '{}')).toMatchObject({
                identity: { host, userUuid: 'current-user' },
                tokens: { accessToken: 'example-rotated-access' },
            })
        } finally {
            AppState.currentState = previousState
            jest.useRealTimers()
        }
    })
})
