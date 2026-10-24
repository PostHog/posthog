import { act, renderHook } from '@testing-library/react-native'
import { AppState, type AppStateStatus } from 'react-native'

import { useAuthStore } from '@/auth/authStore'

import { setAnalyticsClient } from './analytics'
import { FEATURE_FLAGS, useMobileProductFlags } from './featureFlags'
import { initAnalytics } from './posthogClient'

const mockClient = {
    register: jest.fn(),
    capture: jest.fn(),
    screen: jest.fn(),
    captureException: jest.fn(),
    identify: jest.fn(),
    reset: jest.fn(),
    resetPersonPropertiesForFlags: jest.fn(),
    setPersonPropertiesForFlags: jest.fn(),
    reloadFeatureFlagsAsync: jest.fn<Promise<Record<string, boolean | string> | undefined>, []>(),
}
jest.mock('posthog-react-native', () => ({ __esModule: true, default: jest.fn(() => mockClient) }))

describe('mobile feature flag identity', () => {
    test('targets the signed-in email and discards flags from an earlier account or foreground request', async () => {
        const originalKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
        process.env.EXPO_PUBLIC_POSTHOG_KEY = 'phc_example_mobile_test'
        let appChange!: (state: AppStateStatus) => void
        const listener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, callback) => {
            appChange = callback
            return { remove: jest.fn() }
        })
        const requests: ((flags: Record<string, boolean | string>) => void)[] = []
        mockClient.reloadFeatureFlagsAsync.mockImplementation(
            () =>
                new Promise((resolve) => {
                    requests.push(resolve)
                })
        )
        useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null })
        try {
            initAnalytics()
            const { result, unmount } = renderHook(useMobileProductFlags)
            expect(result.current).toEqual({ errors: false, replay: false })

            act(() =>
                useAuthStore.setState({
                    status: 'signed_in',
                    signedIn: true,
                    host: 'https://app.example.com',
                    projectId: 2,
                    user: {
                        id: 1,
                        uuid: 'user-one',
                        distinctId: 'user-one',
                        email: ' First@Example.com ',
                        name: 'First',
                    },
                })
            )
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: 'first@example.com' },
                false
            )
            await act(async () => requests[0]?.({ [FEATURE_FLAGS.sessionReplay]: true }))
            expect(result.current).toEqual({ errors: false, replay: true })

            act(() => appChange('active'))
            act(() =>
                useAuthStore.setState({
                    user: {
                        id: 2,
                        uuid: 'user-two',
                        distinctId: 'user-two',
                        email: 'second@example.com',
                        name: 'Second',
                    },
                })
            )
            expect(result.current).toEqual({ errors: false, replay: false })
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: 'second@example.com' },
                false
            )
            await act(async () => requests[1]?.({ [FEATURE_FLAGS.sessionReplay]: true }))
            expect(result.current).toEqual({ errors: false, replay: false })
            await act(async () => requests[2]?.({ [FEATURE_FLAGS.errorTracking]: true }))
            expect(result.current).toEqual({ errors: true, replay: false })

            act(() => appChange('active'))
            act(() => useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null }))
            await act(async () => requests[3]?.({ [FEATURE_FLAGS.errorTracking]: true }))
            expect(result.current).toEqual({ errors: false, replay: false })
            unmount()
        } finally {
            setAnalyticsClient(null)
            listener.mockRestore()
            if (originalKey === undefined) {
                delete process.env.EXPO_PUBLIC_POSTHOG_KEY
            } else {
                process.env.EXPO_PUBLIC_POSTHOG_KEY = originalKey
            }
        }
    })
})
