import AsyncStorage from '@react-native-async-storage/async-storage'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

describe('persisted launch gates', () => {
    afterEach(async () => {
        jest.restoreAllMocks()
        await AsyncStorage.clear()
    })

    test('auth restore reaches signed out when AsyncStorage cannot be read', async () => {
        jest.spyOn(AsyncStorage, 'getItem').mockRejectedValueOnce(new Error('Storage unavailable'))
        let auth: typeof import('@/auth/authStore') | undefined
        jest.isolateModules(() => {
            auth = jest.requireActual<typeof import('@/auth/authStore')>('@/auth/authStore')
        })
        if (!auth) {
            throw new Error('Auth store did not load')
        }
        await auth.useAuthStore.getState().restore()
        expect(auth.useAuthStore.getState().status).toBe('signed_out')
    })

    test('push registration does not wait forever when AsyncStorage cannot be read', async () => {
        jest.spyOn(AsyncStorage, 'getItem').mockRejectedValueOnce(new Error('Storage unavailable'))
        let push: typeof import('@/features/notifications/pushStore') | undefined
        jest.isolateModules(() => {
            push = jest.requireActual<typeof import('@/features/notifications/pushStore')>(
                '@/features/notifications/pushStore'
            )
        })
        if (!push) {
            throw new Error('Push store did not load')
        }
        await push.waitForPushHydration()
        expect(push.usePushStore.getState()).toMatchObject({ token: null, registeredFor: null })
    })
})
