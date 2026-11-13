import { render, within } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { EMPTY_LIVE_SNAPSHOT } from '@/model/live'

import type { LiveFeed } from './hooks'
import { LiveScreen } from './LiveScreen'

jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'))
jest.mock('react-native-keyboard-controller', () => require('react-native-keyboard-controller/jest'))
jest.mock('react-native-worklets', () => require('react-native-worklets/src/mock'))
jest.mock('expo-router', () => ({
    useRouter: () => ({ canGoBack: () => true, back: jest.fn(), push: jest.fn() }),
    useFocusEffect: jest.fn(),
    useIsFocused: () => true,
}))
jest.mock('@/features/views/useViewsContext', () => ({
    useViewsContext: () => ({ access: { state: 'ok' }, scope: null, identity: 'demo' }),
}))
jest.mock('@/features/views/pointSheet/ChartSheetsProvider', () => ({
    ChartSheetsProvider: ({ children }: { children: ReactNode }): ReactNode => children,
}))
jest.mock('./hooks', () => ({ useLiveFeed: () => mockFeed }))
jest.mock('./map/WorldMapCanvas', () => ({ WorldMapCanvas: () => null }))

let mockFeed: LiveFeed

const insets = {
    frame: { x: 0, y: 0, width: 390, height: 844 },
    insets: { top: 44, bottom: 34, left: 0, right: 0 },
}

describe('LiveScreen', () => {
    test('keeps the table labels with the retained rows until the new top list succeeds', () => {
        mockFeed = {
            snapshot: {
                ...EMPTY_LIVE_SNAPSHOT,
                topPagesMode: 'screens',
                topPages: [{ key: 'Home', label: 'Home', views: 3, percent: 100, rankDelta: null, direct: false }],
            },
            state: 'app_only',
            status: 'live',
            screenActive: true,
            updatedAt: null,
            usersOnline: null,
            paused: false,
            reading: false,
            loadFailed: false,
            pulling: false,
            pull: jest.fn(),
            pause: jest.fn(),
            resume: jest.fn(),
            retry: jest.fn(),
        }
        const screen = (): ReactElement => (
            <SafeAreaProvider initialMetrics={insets}>
                <LiveScreen from="tab" chrome="tab" />
            </SafeAreaProvider>
        )
        const view = render(screen())
        expect(within(view.getByTestId('live-top-screens')).getByText('Screen')).toBeTruthy()

        mockFeed = { ...mockFeed, state: 'web', status: 'reconnecting' }
        view.rerender(screen())
        const table = within(view.getByTestId('live-top-screens'))
        expect(table.getByText('Top screens (last 30 minutes)')).toBeTruthy()
        expect(table.getByText('Screen')).toBeTruthy()
        expect(table.getByText('Home')).toBeTruthy()
        expect(view.queryByTestId('live-top-pages')).toBeNull()

        mockFeed = { ...mockFeed, snapshot: { ...mockFeed.snapshot, topPagesMode: 'pages' }, status: 'live' }
        view.rerender(screen())
        expect(within(view.getByTestId('live-top-pages')).getByText('Path')).toBeTruthy()
        expect(view.queryByTestId('live-top-screens')).toBeNull()
        view.unmount()
    })
})
