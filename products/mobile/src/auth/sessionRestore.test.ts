import * as SecureStore from 'expo-secure-store'
import { installAuthProvider, useAuthStore } from './authStore'
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

    test('restores and refreshes using the secure identity when cached metadata belongs to an earlier account', async () => {
        const requests: string[] = []
        globalThis.fetch = jest.fn(async (url: string) => {
            requests.push(url)
            if (url.endsWith('/oauth/token')) {
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
        await saveTokens(tokens, { host, clientId: 'example-client', method: 'oauth', userUuid: 'current-user' })
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
        await useAuthStore.getState().restore()
        expect(requests).toEqual([`${host}/oauth/token`, `${host}/api/users/@me/`])
        expect(useAuthStore.getState()).toMatchObject({
            host,
            clientId: 'example-client',
            user: { uuid: 'current-user' },
            projectId: null,
            projects: [],
        })
        expect(JSON.parse((await SecureStore.getItemAsync('posthog_mobile_session')) ?? '{}')).toMatchObject({
            identity: { host, userUuid: 'current-user' },
            tokens: { accessToken: 'example-rotated-access' },
        })
    })
})
