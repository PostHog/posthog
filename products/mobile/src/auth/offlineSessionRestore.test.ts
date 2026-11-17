import AsyncStorage from '@react-native-async-storage/async-storage'
import * as SecureStore from 'expo-secure-store'

import { accountKey } from './accountKey'
import { installAuthProvider, useAuthStore } from './authStore'

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

jest.mock('expo-crypto', () => ({
    CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
    digestStringAsync: async (_algorithm: string, value: string) => Buffer.from(value).toString('hex'),
}))

describe('offline session restoration', () => {
    it('keeps the signed-in account and its project after an upgrade from the single-account app, offline', async () => {
        const host = 'https://example.com'
        const user = { uuid: 'example-user', distinctId: 'example-user', email: 'example@example.com', name: 'Example' }
        // The single-account app kept one session item and one set of account fields.
        await SecureStore.setItemAsync(
            'posthog_mobile_session',
            JSON.stringify({
                version: 1,
                identity: { host, clientId: 'example-client', method: 'oauth', userUuid: 'example-user' },
                tokens: {
                    kind: 'oauth',
                    accessToken: 'example-access',
                    refreshToken: 'example-refresh',
                    expiresAt: 0,
                    grantedScopes: null,
                    requestedScopes: null,
                },
            })
        )
        await AsyncStorage.setItem(
            'posthog-mobile-auth',
            JSON.stringify({
                version: 1,
                state: {
                    region: 'custom',
                    host,
                    clientId: 'example-client',
                    method: 'oauth',
                    user,
                    organizations: [],
                    projects: [
                        {
                            id: 1,
                            name: 'Example project',
                            organizationId: 'example-org',
                            organizationName: 'Example organization',
                        },
                    ],
                    projectId: 1,
                    projectName: 'Example project',
                },
            })
        )
        await useAuthStore.persist.rehydrate()
        globalThis.fetch = jest.fn(async () => {
            throw new TypeError('Offline')
        }) as typeof fetch
        installAuthProvider()

        await useAuthStore.getState().restore()

        const key = await accountKey(host, 'example-user')
        expect(useAuthStore.getState()).toMatchObject({
            status: 'signed_in',
            signedIn: true,
            host,
            user: { uuid: 'example-user' },
            projectId: 1,
            activeAccountKey: key,
            accounts: [{ key, host, user: { email: 'example@example.com' }, projectId: 1, needsSignIn: false }],
        })
        expect(await SecureStore.getItemAsync('posthog_mobile_session')).toBeNull()
    })
})
