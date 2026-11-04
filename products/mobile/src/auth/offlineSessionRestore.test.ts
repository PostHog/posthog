import { installAuthProvider, useAuthStore } from './authStore'
import { saveTokens, setSessionTokens } from './tokens'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-secure-store', () => {
    const values = new Map<string, string>()
    return {
        getItemAsync: async (key: string) => values.get(key) ?? null,
        setItemAsync: async (key: string, value: string) => {
            values.set(key, value)
        },
        deleteItemAsync: async (key: string) => {
            values.delete(key)
        },
    }
})

describe('offline session restoration', () => {
    it('keeps an existing verified owner and selected project when refresh and account reads are offline', async () => {
        await useAuthStore.persist.rehydrate()
        const host = 'https://example.com'
        await saveTokens(
            {
                kind: 'oauth',
                accessToken: 'example-access',
                refreshToken: 'example-refresh',
                expiresAt: 0,
                grantedScopes: null,
                requestedScopes: null,
            },
            { host, clientId: 'example-client', method: 'oauth', userUuid: 'example-user' }
        )
        useAuthStore.setState({
            status: 'loading',
            signedIn: false,
            clientId: 'example-client',
            method: 'oauth',
            host,
            user: { uuid: 'example-user', distinctId: 'example-user', email: 'example@example.com', name: 'Example' },
            projectId: 1,
            projects: [
                {
                    id: 1,
                    name: 'Example project',
                    organizationId: 'example-org',
                    organizationName: 'Example organization',
                },
            ],
        })
        setSessionTokens(null)
        globalThis.fetch = jest.fn(async () => {
            throw new TypeError('Offline')
        }) as typeof fetch
        installAuthProvider()
        await useAuthStore.getState().restore()
        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            signedIn: true,
            host,
            user: { uuid: 'example-user' },
            projectId: 1,
        })
    })
})
