import { fireEvent, render, within } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { useTabHeaderStore } from '@/features/tabs/tabHeaderStore'
import { EMPTY_LIVE_SNAPSHOT } from '@/model/live'

import type { LiveFeed } from './hooks'
import { LiveAudienceControl } from './LiveAudienceControl'
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
    test('offers All, Web and Mobile and defaults to All', () => {
        const view = render(
            <SafeAreaProvider initialMetrics={insets}>
                <LiveAudienceControl />
            </SafeAreaProvider>
        )
        expect(view.getByText('All')).toBeTruthy()
        fireEvent.press(view.getByTestId('live-audience-control'))
        expect(view.getByTestId('live-audience-menu-all')).toBeTruthy()
        expect(view.getByTestId('live-audience-menu-web')).toBeTruthy()
        expect(view.getByTestId('live-audience-menu-mobile')).toBeTruthy()
        expect(view.queryByText('Auto')).toBeNull()
        expect(view.queryByText('Both')).toBeNull()
        view.unmount()
    })

    test.each(['web', 'mobile', 'mixed'] as const)(
        'hides an empty location map for %s without hiding other cards',
        (kind) => {
            mockFeed = feed()
            mockFeed.state = kind === 'mobile' ? 'app_only' : 'web'
            mockFeed.snapshot = {
                ...mockFeed.snapshot,
                profile: { kind },
                topPagesMode: kind === 'mobile' ? 'screens' : 'pages',
                world: { total: 0, countries: [], counts: {} },
            }
            const view = render(screen())
            expect(view.queryByTestId('live-map')).toBeNull()
            expect(view.getByTestId('live-activity')).toBeTruthy()
            mockFeed.snapshot = {
                ...mockFeed.snapshot,
                world: {
                    total: 1,
                    countries: [{ key: 'US', label: 'United States', flag: null, count: 1, percent: 100 }],
                    counts: { US: 1 },
                },
            }
            view.rerender(screen())
            expect(view.getByTestId('live-map')).toBeTruthy()
            view.unmount()
        }
    )

    test('keeps the location retry card while the location result is unknown', () => {
        mockFeed = feed()
        const view = render(screen())
        expect(view.getByTestId('live-map-not-loaded')).toBeTruthy()
        view.unmount()
    })

    test.each([false, true])('shows loading rather than failed cards for a pending audience, paused=%s', (paused) => {
        mockFeed = { ...feed(), paused, reading: !paused, status: paused ? 'paused' : 'loading' }
        mockFeed.snapshot = {
            ...EMPTY_LIVE_SNAPSHOT,
            profile: { kind: 'mobile' },
            preference: 'mobile',
            topPagesMode: 'screens',
        }
        const view = render(screen())
        expect(view.getByTestId('live-loading')).toBeTruthy()
        expect(view.queryByTestId('live-map-not-loaded')).toBeNull()
        expect(view.queryByTestId('live-activity-not-loaded')).toBeNull()
        expect(view.queryByTestId('live-paused-banner')).toBeNull()
        view.unmount()
    })

    test('keeps an undetected profile neutral while waiting for a read', () => {
        mockFeed = { ...feed(), state: 'web', paused: true, status: 'paused' }
        mockFeed.snapshot = { ...EMPTY_LIVE_SNAPSHOT, profile: { kind: 'unknown' } }
        const view = render(screen())
        expect(view.queryByText('Web analytics')).toBeNull()
        view.unmount()
    })

    test('shows mobile metrics and platforms without browser or referrer controls', () => {
        mockFeed = feed()
        mockFeed.snapshot = {
            ...mockFeed.snapshot,
            profile: { kind: 'mobile' },
            mobileMetrics: {
                dailyActiveUsers: 342,
                weeklyActiveUsers: 1846,
                installs: 27,
                weeklyInstalls: 193,
                sessions: 18,
                updatedAt: Date.now(),
            },
            platforms: {
                total: 12,
                statLabel: 'unique users',
                rows: [{ key: 'iOS', label: 'iOS', flag: null, count: 12, percent: 100 }],
            },
        }
        const view = render(screen())
        expect(view.getByTestId('live-stat-dau').props.children).toBe('342')
        expect(view.getByTestId('live-stat-wau').props.children).toBe('1,846')
        expect(view.getByTestId('live-stat-installs-week').props.children).toBe('193')
        expect(view.getByTestId('live-stat-screenviews')).toBeTruthy()
        expect(view.getByText('Where users are')).toBeTruthy()
        expect(view.getByText('Platforms')).toBeTruthy()
        expect(view.getByText('iOS')).toBeTruthy()
        expect(view.queryByTestId('live-breakdown-browsers')).toBeNull()
        expect(view.queryByTestId('live-top-referrers')).toBeNull()
        view.unmount()
    })

    test('keeps combined user counts separate from mobile metrics and lists both pages and screens', () => {
        mockFeed = feed()
        mockFeed.snapshot = {
            ...mockFeed.snapshot,
            profile: { kind: 'mixed' },
            topPagesMode: 'pages',
            topScreens: mockFeed.snapshot.topPages,
        }
        const view = render(screen())
        expect(view.getByTestId('live-top-pages')).toBeTruthy()
        expect(view.getByTestId('live-top-screens')).toBeTruthy()
        expect(view.getByTestId('live-mobile-metrics')).toBeTruthy()
        expect(view.getByTestId('live-stat-dau').props.children).toBe('–')
        view.unmount()
    })

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

    test('publishes the audience selector instead of Pause to the shared header', () => {
        mockFeed = feed()
        const view = render(screen())
        expect(useTabHeaderStore.getState().slots.live?.liveAudience).toBe(true)
        expect(view.queryByTestId('live-pause')).toBeNull()
        expect(view.queryByTestId('live-audience-control')).toBeNull()
        expect(
            view.queryByText('Users online covers the whole project. Other metrics show mobile activity.')
        ).toBeNull()
        view.unmount()
    })
})
