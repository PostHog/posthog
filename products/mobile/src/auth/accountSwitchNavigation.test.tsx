import { Redirect, router, useLocalSearchParams } from 'expo-router'
import { act, renderRouter, screen } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'

import RootLayout from '../../app/_layout'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-keyboard-controller', () => ({ KeyboardProvider: require('react-native').View }))
jest.mock('@/auth/BootSplash', () => ({ BootSplash: require('react-native').View }))
jest.mock('expo-splash-screen', () => ({
    preventAutoHideAsync: jest.fn(async () => undefined),
    setOptions: jest.fn(),
    hideAsync: jest.fn(async () => undefined),
}))
jest.mock('@/demo/demoMode', () => ({
    useDemoHydrated: () => true,
    useDataMode: () => 'live',
    useDemoMode: Object.assign((selector: (state: { enabled: boolean }) => unknown) => selector({ enabled: false }), {
        getState: () => ({ enabled: false }),
    }),
}))
jest.mock('@/features/chat/draftPersistence', () => ({}))
jest.mock('@/features/hedgehog/useHedgehogWidgetSync', () => ({ useHedgehogWidgetSync: jest.fn() }))
jest.mock('@/features/widgets/useChartWidgetSync', () => ({ useChartWidgetSync: jest.fn() }))
jest.mock('@/features/notifications/pushRegistration', () => ({ configureNotifications: jest.fn() }))
jest.mock('@/features/notifications/usePushRegistration', () => ({ usePushRegistration: jest.fn() }))
jest.mock('@/features/notifications/useNotificationRouting', () => ({ useNotificationRouting: jest.fn() }))
jest.mock('@/lib/posthogClient', () => ({ initAnalytics: jest.fn() }))

function Index(): ReactElement {
    return <Redirect href="/inbox" />
}

function Inbox(): ReactElement {
    return <View testID="inbox-screen" />
}

function Report(): ReactElement {
    const { id } = useLocalSearchParams<{ id: string }>()
    return <Text testID="report-screen">{id}</Text>
}

describe('screens across an account switch', () => {
    test("another account's session opens on the start page, with no screen of the earlier account left", async () => {
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://us.posthog.com',
            user: { uuid: 'ada', distinctId: 'ada', email: 'ada@example.com', name: 'Ada' },
            projectId: 2,
            activeAccountKey: 'account-a',
            restore: async () => undefined,
        })
        const app = await renderRouter(
            { _layout: RootLayout, index: Index, inbox: Inbox, 'report/[id]': Report },
            { initialUrl: '/inbox' }
        )
        act(() => router.push('/report/ada-report'))
        expect(screen.getByTestId('report-screen').props.children).toBe('ada-report')

        // One store update with no loading state in between, as a fast switch can publish.
        act(() => {
            useAuthStore.setState({
                host: 'https://eu.posthog.com',
                user: { uuid: 'bob', distinctId: 'bob', email: 'bob@example.com', name: 'Bob' },
                activeAccountKey: 'account-b',
            })
        })

        expect(app.getPathname()).toBe('/inbox')
        expect(screen.queryByTestId('report-screen')).toBeNull()
    })
})
