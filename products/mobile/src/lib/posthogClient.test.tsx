import { act, renderHook } from '@testing-library/react-native'
import { AppState, type AppStateStatus } from 'react-native'

import { useAuthStore } from '@/auth/authStore'

import { setAnalyticsClient } from './analytics'
import { FEATURE_FLAGS, useMobileProductFlags } from './featureFlags'
import { initAnalytics } from './posthogClient'

let mockFlagProperties: Record<string, string | number | null> = {}
const mockClient = {
    register: jest.fn(),
    capture: jest.fn(),
    screen: jest.fn(),
    captureException: jest.fn(),
    identify: jest.fn(),
    reset: jest.fn(),
    resetPersonPropertiesForFlags: jest.fn(() => {
        mockFlagProperties = {}
    }),
    setPersonPropertiesForFlags: jest.fn((properties: typeof mockFlagProperties) => {
        mockFlagProperties = { ...mockFlagProperties, ...properties }
    }),
    reloadFeatureFlagsAsync: jest.fn<Promise<Record<string, boolean | string> | undefined>, []>(),
}
jest.mock('posthog-react-native', () => ({ __esModule: true, default: jest.fn(() => mockClient) }))

describe('mobile feature flag identity', () => {
    test('respects email privacy and discards flags from an earlier account or privacy context', async () => {
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
        mockFlagProperties = { email: 'previous@example.com' }
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            projectId: 2,
            user: {
                uuid: 'persisted-user',
                distinctId: 'persisted-user',
                email: 'persisted@example.com',
                name: 'Example',
            },
        })
        try {
            initAnalytics()
            expect(mockFlagProperties).toEqual({ project_id: 2, email: null })
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
                        anonymizeData: false,
                        name: 'First',
                    },
                })
            )
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: 'first@example.com' },
                false
            )
            await act(async () => requests[1]?.({ [FEATURE_FLAGS.sessionReplay]: true }))
            expect(result.current).toEqual({ errors: false, replay: true })

            const secondUser = {
                id: 2,
                uuid: 'user-two',
                distinctId: 'user-two',
                email: 'second@example.com',
                anonymizeData: false,
                name: 'Second',
            }
            act(() => appChange('active'))
            act(() => useAuthStore.setState({ user: secondUser }))
            expect(result.current).toEqual({ errors: false, replay: false })
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: 'second@example.com' },
                false
            )
            await act(async () => requests[2]?.({ [FEATURE_FLAGS.sessionReplay]: true }))
            expect(result.current).toEqual({ errors: false, replay: false })
            await act(async () => requests[3]?.({ [FEATURE_FLAGS.errorTracking]: true }))
            expect(result.current).toEqual({ errors: true, replay: false })

            act(() => appChange('active'))
            const previousEmailRequest = requests.at(-1)
            act(() => useAuthStore.setState({ user: { ...secondUser, anonymizeData: true } }))
            expect(mockFlagProperties).toEqual({ project_id: 2, email: null })
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: null },
                false
            )
            expect(result.current).toEqual({ errors: false, replay: false })
            await act(async () => previousEmailRequest?.({ [FEATURE_FLAGS.errorTracking]: true }))
            expect(result.current).toEqual({ errors: false, replay: false })
            await act(async () => requests.at(-1)?.({ [FEATURE_FLAGS.errorTracking]: true }))
            expect(result.current).toEqual({ errors: true, replay: false })

            act(() => useAuthStore.setState({ user: { ...secondUser, anonymizeData: undefined } }))
            expect(mockClient.setPersonPropertiesForFlags).toHaveBeenLastCalledWith(
                { project_id: 2, email: null },
                false
            )

            act(() => appChange('active'))
            act(() => useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null }))
            await act(async () => requests.at(-1)?.({ [FEATURE_FLAGS.errorTracking]: true }))
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
