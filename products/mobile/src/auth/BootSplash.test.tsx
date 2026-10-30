import { act, fireEvent, render, screen } from '@testing-library/react-native'
import * as SplashScreen from 'expo-splash-screen'

import { track } from '@/lib/analytics'

import RootLayout from '../../app/_layout'
import { useAuthStore } from './authStore'
import { SPLASH_TIMEOUT_MS, useBootGate } from './bootGate'

jest.mock('expo-router', () => {
    const { createElement } = jest.requireActual<typeof import('react')>('react')
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    const segments = ['(tabs)', 'inbox']
    return {
        Stack: Object.assign(() => createElement(View, { testID: 'app-screens' }), { Screen: () => null }),
        useSegments: () => segments,
    }
})
jest.mock('expo-splash-screen', () => ({
    preventAutoHideAsync: jest.fn(async () => undefined),
    setOptions: jest.fn(),
    hideAsync: jest.fn(async () => undefined),
}))
jest.mock('react-native-gesture-handler', () => ({ GestureHandlerRootView: require('react-native').View }))
jest.mock('react-native-keyboard-controller', () => ({ KeyboardProvider: require('react-native').View }))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('@/auth/authStore', () => {
    const { create } = jest.requireActual<typeof import('zustand')>('zustand')
    return {
        installAuthProvider: jest.fn(),
        useAuthStore: create(() => ({ status: 'loading', restore: async () => undefined })),
    }
})
jest.mock('@/auth/useAuthRedirect', () => ({ useAuthRedirect: jest.fn() }))
jest.mock('@/demo/demoMode', () => ({ useDemoHydrated: () => true }))
jest.mock('@/ui/appearanceStore', () => ({
    ...jest.requireActual('@/ui/appearanceStore'),
    useAppearanceHydrated: () => true,
}))
jest.mock('@/features/ai/AiApprovalDialog', () => ({ AiApprovalDialog: () => null }))
jest.mock('@/features/updates/useAutomaticUpdates', () => ({ useAutomaticUpdates: jest.fn() }))
jest.mock('@/features/chat/draftPersistence', () => ({}))
jest.mock('@/features/hedgehog/useHedgehogWidgetSync', () => ({ useHedgehogWidgetSync: jest.fn() }))
jest.mock('@/features/notifications/pushRegistration', () => ({ configureNotifications: jest.fn() }))
jest.mock('@/features/notifications/useNotificationRouting', () => ({ useNotificationRouting: jest.fn() }))
jest.mock('@/features/notifications/usePushRegistration', () => ({ usePushRegistration: jest.fn() }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('@/lib/posthogClient', () => ({ initAnalytics: jest.fn() }))
jest.mock('@/lib/useScreenTracking', () => ({ useScreenTracking: jest.fn() }))
jest.mock('@/ui/RouteErrorBoundary', () => ({ RouteErrorBoundary: jest.fn() }))
jest.mock('@/ui/icons/AnimatedLogomark', () => ({ AnimatedLogomark: require('react-native').View }))

describe('boot splash handoff', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.clearAllMocks()
        useAuthStore.setState({ status: 'loading' })
        useBootGate.setState({ firstScreenReady: false })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each(['first_screen', 'timeout'] as const)(
        'reveals the animated splash before the session loads and keeps it until %s',
        (reason) => {
            render(<RootLayout />)
            fireEvent(screen.getByTestId('boot-splash'), 'layout')

            expect(SplashScreen.hideAsync).toHaveBeenCalledTimes(1)
            expect(screen.getByLabelText('Loading PostHog')).toBeTruthy()
            expect(screen.queryByTestId('app-screens')).toBeNull()

            act(() => useAuthStore.setState({ status: 'signed_in' }))
            expect(screen.getByTestId('app-screens')).toBeTruthy()
            expect(screen.getByTestId('boot-splash')).toBeTruthy()

            act(() => {
                if (reason === 'first_screen') {
                    useBootGate.getState().markFirstScreenReady()
                } else {
                    jest.advanceTimersByTime(SPLASH_TIMEOUT_MS)
                }
            })
            expect(screen.queryByTestId('boot-splash')).toBeNull()
            expect(track).toHaveBeenCalledWith('mobile_splash_hidden', expect.objectContaining({ reason }))
        }
    )
})
