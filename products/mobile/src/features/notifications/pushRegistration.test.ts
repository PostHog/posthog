import * as Notifications from 'expo-notifications'

import { registerPushToken, unregisterPushToken } from '@/api/pushTokens'
import { useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'

import { syncPushRegistration, unregisterPush } from './pushRegistration'
import { usePushStore, waitForPushHydration } from './pushStore'

jest.mock('expo-notifications', () => ({
    getPermissionsAsync: jest.fn(),
    requestPermissionsAsync: jest.fn(),
    getExpoPushTokenAsync: jest.fn(),
    setNotificationChannelAsync: jest.fn(),
    IosAuthorizationStatus: { PROVISIONAL: 3 },
}))
jest.mock('expo-constants', () => ({ expoConfig: { extra: { eas: { projectId: 'test-project' } } } }))
jest.mock('@/api/pushTokens', () => ({ registerPushToken: jest.fn(), unregisterPushToken: jest.fn() }))
jest.mock('./pushSupport', () => ({ notificationsSupported: () => true, pushUnavailableReason: () => null }))

const register = registerPushToken as jest.MockedFunction<typeof registerPushToken>
const unregister = unregisterPushToken as jest.MockedFunction<typeof unregisterPushToken>
const permissions = Notifications.getPermissionsAsync as jest.MockedFunction<typeof Notifications.getPermissionsAsync>
const expoToken = Notifications.getExpoPushTokenAsync as jest.MockedFunction<typeof Notifications.getExpoPushTokenAsync>
const KEY = 'https://us.posthog.com|user-1'

async function tick(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('push registration across session transitions', () => {
    beforeEach(async () => {
        await waitForPushHydration()
        setSessionTokens({
            kind: 'personal_api_key',
            accessToken: 'session-token',
            refreshToken: null,
            expiresAt: null,
            grantedScopes: null,
            requestedScopes: null,
        })
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://us.posthog.com',
            user: { uuid: 'user-1', distinctId: 'user-1', email: 'user@example.com', name: 'User' },
        })
        usePushStore.setState({
            permission: 'unknown',
            canAskAgain: true,
            token: null,
            registeredFor: null,
            prompted: false,
            registering: false,
            error: null,
        })
        register.mockReset().mockResolvedValue(undefined)
        unregister.mockReset().mockResolvedValue(undefined)
        permissions.mockReset().mockResolvedValue({ granted: true, status: 'granted', canAskAgain: true } as never)
        expoToken.mockReset().mockResolvedValue({ data: 'ExponentPushToken[new]' } as never)
    })

    test('sign out waits for a first registration POST and then deletes its possibly accepted token', async () => {
        let finishPost: () => void = () => undefined
        let postStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            postStarted = resolve
        })
        register.mockImplementationOnce(
            () =>
                new Promise<void>((resolve) => {
                    postStarted()
                    finishPost = resolve
                })
        )
        const syncing = syncPushRegistration('never')
        await started
        const cleanup = unregisterPush()
        expect(unregister).not.toHaveBeenCalled()
        finishPost()
        await syncing
        const recover = await cleanup
        expect(unregister).toHaveBeenCalledWith('ExponentPushToken[new]', expect.anything())
        expect(usePushStore.getState().token).toBeNull()
        recover()
    })

    test('a failed POST retains the attempted token for cleanup and Settings retry', async () => {
        register.mockRejectedValueOnce(new Error('Network response lost'))
        await syncPushRegistration('never')
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[new]', registeredFor: KEY })
        expect(usePushStore.getState().error).toBeTruthy()

        await syncPushRegistration('always')
        expect(register).toHaveBeenCalledTimes(2)
        expect(usePushStore.getState()).toMatchObject({
            token: 'ExponentPushToken[new]',
            registeredFor: KEY,
            error: null,
        })
    })

    test('a failed rotation delete retains the old token and retries before registering the new one', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        unregister.mockRejectedValueOnce(new Error('Offline'))
        await syncPushRegistration('never')
        expect(register).not.toHaveBeenCalled()
        expect(usePushStore.getState().token).toBe('ExponentPushToken[old]')
        expect(usePushStore.getState().error).toBeTruthy()

        await syncPushRegistration('never')
        expect(unregister).toHaveBeenCalledTimes(2)
        expect(register).toHaveBeenCalledTimes(1)
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[new]', error: null })
    })

    test('a session ending during rotation delete never registers the next token', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        let finishDelete: () => void = () => undefined
        let deleteStarted: () => void = () => undefined
        const started = new Promise<void>((resolve) => {
            deleteStarted = resolve
        })
        unregister.mockImplementationOnce(
            () =>
                new Promise<void>((resolve) => {
                    deleteStarted()
                    finishDelete = resolve
                })
        )
        const syncing = syncPushRegistration('never')
        await started
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_out', signedIn: false })
        finishDelete()
        await syncing
        expect(register).not.toHaveBeenCalled()
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[old]', registering: false })
    })

    test('failed cleanup preserves the token and a later attempt can finish', async () => {
        usePushStore.setState({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        unregister.mockRejectedValueOnce(new Error('Offline'))
        await expect(unregisterPush()).rejects.toThrow('try again')
        expect(usePushStore.getState()).toMatchObject({ token: 'ExponentPushToken[old]', registeredFor: KEY })
        const recover = await unregisterPush()
        expect(unregister).toHaveBeenCalledTimes(2)
        expect(usePushStore.getState().token).toBeNull()
        recover()
        await tick()
    })
})
