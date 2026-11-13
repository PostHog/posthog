import { act, render, within } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { useTabHeaderStore } from '@/features/tabs/tabHeaderStore'
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
jest.mock('./LiveMeanwhile', () => ({ LiveMeanwhile: () => null }))

let mockFeed: LiveFeed

const insets = {
    frame: { x: 0, y: 0, width: 390, height: 844 },
    insets: { top: 44, bottom: 34, left: 0, right: 0 },
}

function feed(): LiveFeed {
    return {
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
}

function screen(): ReactElement {
    return (
        <SafeAreaProvider initialMetrics={insets}>
            <LiveScreen from="tab" chrome="tab" />
        </SafeAreaProvider>
    )
}

describe('LiveScreen', () => {
    test('keeps the table labels with the retained rows until the new top list succeeds', () => {
        mockFeed = feed()
        const view = render(screen())
        expect(within(view.getByTestId('live-top-screens')).getByText('Screen')).toBeTruthy()
        expect(useTabHeaderStore.getState().slots.live?.status).toBeNull()

        mockFeed = { ...mockFeed, state: 'web', status: 'reconnecting' }
        view.rerender(screen())
        const table = within(view.getByTestId('live-top-screens'))
        expect(table.getByText('Top screens (last 30 minutes)')).toBeTruthy()
        expect(table.getByText('Screen')).toBeTruthy()
        expect(table.getByText('Home')).toBeTruthy()
        expect(view.queryByTestId('live-top-pages')).toBeNull()
        expect(useTabHeaderStore.getState().slots.live?.status).toBe('Reconnecting…')

        view.unmount()
        const revisited = render(screen())
        expect(useTabHeaderStore.getState().slots.live?.status).toBe('Reconnecting…')

        mockFeed = { ...mockFeed, snapshot: { ...mockFeed.snapshot, topPagesMode: 'pages' }, status: 'live' }
        revisited.rerender(screen())
        expect(within(revisited.getByTestId('live-top-pages')).getByText('Path')).toBeTruthy()
        expect(revisited.queryByTestId('live-top-screens')).toBeNull()
        expect(useTabHeaderStore.getState().slots.live?.status).toBeNull()
        revisited.unmount()
    })

    test('gives the tabs header a Pause that follows the feed, and none for a project without events', () => {
        const headerPause = (): { paused: boolean; onPress: () => void } | null | undefined =>
            useTabHeaderStore.getState().slots.live?.pause
        mockFeed = feed()
        const view = render(screen())
        expect(view.queryByTestId('live-status')).toBeNull()
        expect(headerPause()?.paused).toBe(false)
        act(() => headerPause()?.onPress())
        expect(mockFeed.pause).toHaveBeenCalledTimes(1)

        mockFeed = { ...mockFeed, paused: true, status: 'paused' }
        view.rerender(screen())
        expect(headerPause()?.paused).toBe(true)
        act(() => headerPause()?.onPress())
        expect(mockFeed.resume).toHaveBeenCalledTimes(1)
        expect(mockFeed.pause).toHaveBeenCalledTimes(1)

        mockFeed = { ...mockFeed, paused: false, status: 'live', state: 'not_set_up' }
        view.rerender(screen())
        expect(headerPause()).toBeNull()
        view.unmount()
    })
})
