import { act, fireEvent, render, renderHook, within } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { useTabHeaderStore } from '@/features/tabs/tabHeaderStore'
import { EMPTY_LIVE_SNAPSHOT } from '@/model/live'
import { DEFAULT_LIVE_TRAFFIC_FILTERS } from '@/model/liveTrafficFilters'

import type { LiveFeed } from './hooks'
import { LiveScreen } from './LiveScreen'
import { useLivePreference } from './livePreference'
import { clearLiveWorldShare, useLiveWorldShare } from './liveWorldStore'

jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'))
jest.mock('react-native-keyboard-controller', () => require('react-native-keyboard-controller/jest'))
jest.mock('react-native-worklets', () => require('react-native-worklets/src/mock'))
jest.mock('expo-router', () => ({
    Stack: {
        Toolbar: {
            Menu: () => null,
            Icon: () => null,
            Badge: () => null,
            Label: () => null,
            MenuAction: () => null,
            Button: () => null,
        },
    },
    useRouter: () => ({ canGoBack: () => true, back: jest.fn(), push: jest.fn() }),
    useFocusEffect: jest.fn(),
    useIsFocused: () => true,
}))
jest.mock('@/features/views/useViewsContext', () => ({
    useViewsContext: () => ({ access: { state: 'ok' }, scope: null, identity: 'demo' }),
}))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'demo',
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

function screen(chrome: 'tab' | 'stack' = 'tab'): ReactElement {
    return (
        <SafeAreaProvider initialMetrics={insets}>
            <LiveScreen from="tab" chrome={chrome} />
        </SafeAreaProvider>
    )
}

describe('LiveScreen', () => {
    test('edits platform and traffic filters together, cancels edits and clears from an empty result', () => {
        mockFeed = { ...feed(), state: 'quiet' }
        const view = render(screen())
        const open = (): void => act(() => useTabHeaderStore.getState().slots.live?.filter?.onPress())
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(0)
        open()
        expect(view.getByLabelText('All')).toBeSelected()
        fireEvent.press(view.getByTestId('live-filter-web'))
        fireEvent(view.getByTestId('live-filter-bots'), 'valueChange', true)
        const edit = (field: string): void => fireEvent.press(view.getByTestId(`live-filter-edit-${field}`))
        const save = (): void => fireEvent.press(view.getByTestId('live-filter-save'))
        edit('hostname')
        fireEvent.changeText(view.getByTestId('live-filter-hostname'), 'https://app.example.com')
        expect(view.getByTestId('live-filter-save')).toBeDisabled()
        fireEvent.changeText(view.getByTestId('live-filter-hostname'), ' APP.EXAMPLE.COM ')
        save()
        edit('pathPrefix')
        expect(view.getByLabelText('Is exactly')).toBeSelected()
        fireEvent.press(view.getByTestId('live-filter-path-prefix'))
        fireEvent.changeText(view.getByTestId('live-filter-path'), 'docs/')
        save()
        edit('referringDomain')
        fireEvent.press(view.getByTestId('live-filter-direct'))
        save()
        edit('channelType')
        fireEvent.changeText(view.getByTestId('live-filter-search'), 'organic')
        fireEvent.press(view.getByTestId('live-filter-option-Organic Search'))
        edit('countryCode')
        fireEvent.changeText(view.getByTestId('live-filter-search'), 'United States')
        fireEvent.press(view.getByTestId('live-filter-option-US'))
        edit('deviceType')
        fireEvent.press(view.getByTestId('live-filter-option-Desktop'))
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(0)
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(view.queryByTestId('live-filter-sheet')).toBeNull()
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(8)
        expect(
            view.getByLabelText(
                'Edit Live filters. Web · app.example.com · Paths starting with /docs/ · Organic Search · Direct entry · United States · Desktop devices · Bots excluded'
            )
        ).toBeTruthy()
        expect(view.getByText('No matching traffic')).toBeTruthy()
        fireEvent.press(view.getByText('Edit filters'))
        expect(view.getByText('app.example.com')).toBeTruthy()
        expect(view.getByText('Paths starting with /docs/')).toBeTruthy()
        expect(view.getByLabelText('Web')).toBeSelected()
        fireEvent.press(view.getByTestId('live-filters-clear'))
        fireEvent.press(view.getByText('Cancel'))
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(8)
        open()
        fireEvent.press(view.getByTestId('live-filters-clear'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(0)
        expect(view.queryByTestId('live-filter-summary')).toBeNull()
        expect(view.getByText('Quiet right now')).toBeTruthy()
        view.unmount()
    })

    test('distinguishes the Mobile platform and Mobile device type in the applied summary', () => {
        mockFeed = feed()
        const view = render(screen())
        const open = (): void => act(() => useTabHeaderStore.getState().slots.live?.filter?.onPress())
        open()
        fireEvent.press(view.getByTestId('live-filter-mobile'))
        fireEvent.press(view.getByTestId('live-filter-edit-deviceType'))
        fireEvent.press(view.getByTestId('live-filter-option-Mobile'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(view.getByText('Mobile · Mobile devices')).toBeTruthy()
        expect(view.getByLabelText('Edit Live filters. Mobile · Mobile devices')).toBeTruthy()
        open()
        fireEvent.press(view.getByTestId('live-filters-clear'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
        view.unmount()
    })

    test('edits individual filter values and preserves custom channels and exact paths', () => {
        mockFeed = feed()
        const view = render(screen())
        const open = (): void => act(() => useTabHeaderStore.getState().slots.live?.filter?.onPress())
        const edit = (field: string): void => fireEvent.press(view.getByTestId(`live-filter-edit-${field}`))
        open()
        edit('pathPrefix')
        fireEvent.changeText(view.getByTestId('live-filter-path'), '/pricing')
        fireEvent.press(view.getByTestId('live-filter-save'))
        edit('referringDomain')
        fireEvent.changeText(view.getByTestId('live-filter-referringDomain'), 'Search.Example.com')
        fireEvent.press(view.getByTestId('live-filter-save'))
        edit('channelType')
        fireEvent.changeText(view.getByTestId('live-filter-search'), 'Partner webinars')
        fireEvent.press(view.getByTestId('live-filter-option-Partner webinars'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(
            view.getByLabelText(
                'Edit Live filters. Path is /pricing · Partner webinars · Entry from search.example.com'
            )
        ).toBeTruthy()
        open()
        edit('channelType')
        fireEvent.press(view.getByTestId('live-filters-clear'))
        edit('pathPrefix')
        fireEvent.changeText(view.getByTestId('live-filter-path'), '/different')
        fireEvent.press(view.getByTestId('live-filter-back'))
        expect(view.getByText('Path is /pricing')).toBeTruthy()
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(2)
        open()
        fireEvent.press(view.getByTestId('live-filters-clear'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
        view.unmount()
    })

    test('hides the banner independently of active filters and restores it from the filter sheet', () => {
        mockFeed = feed()
        const view = render(screen())
        const open = (): void => act(() => useTabHeaderStore.getState().slots.live?.filter?.onPress())
        open()
        fireEvent.press(view.getByTestId('live-filter-mobile'))
        fireEvent.press(view.getByTestId('live-filters-apply'))

        fireEvent.press(view.getByLabelText('Hide filter banner'))
        expect(view.queryByTestId('live-filter-summary')).toBeNull()
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(1)

        open()
        expect(view.getByLabelText('Mobile')).toBeSelected()
        expect(view.getByLabelText('Show filter banner')).toHaveProp('value', false)
        fireEvent(view.getByLabelText('Show filter banner'), 'valueChange', true)
        fireEvent.press(view.getByText('Cancel'))
        expect(view.queryByTestId('live-filter-summary')).toBeNull()

        open()
        fireEvent(view.getByLabelText('Show filter banner'), 'valueChange', true)
        fireEvent.press(view.getByTestId('live-filters-apply'))
        expect(view.getByLabelText('Edit Live filters. Mobile')).toBeTruthy()
        open()
        fireEvent.press(view.getByTestId('live-filters-clear'))
        fireEvent.press(view.getByTestId('live-filters-apply'))
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

    test('shows a loading indicator while the location result is unknown', () => {
        mockFeed = feed()
        const view = render(screen())
        expect(view.getByTestId('live-map-loading')).toBeTruthy()
        view.unmount()
    })

    test('opening a paused Live map shares the country data with its traffic filters', () => {
        const selection = renderHook(() => useLivePreference())
        const trafficFilters = { ...DEFAULT_LIVE_TRAFFIC_FILTERS, countryCode: 'US' }
        act(() => selection.result.current.setLiveFilters('all', trafficFilters))
        const world = {
            total: 1,
            countries: [{ key: 'US', label: 'United States', flag: null, count: 1, percent: 100 }],
            counts: { US: 1 },
        }
        mockFeed = {
            ...feed(),
            state: 'web',
            status: 'paused',
            paused: true,
            snapshot: { ...EMPTY_LIVE_SNAPSHOT, profile: { kind: 'mixed' }, world },
        }
        try {
            const view = render(screen())
            fireEvent.press(view.getByTestId('live-map'))
            expect(useLiveWorldShare.getState()).toMatchObject({ world, paused: true, trafficFilters })
        } finally {
            act(() => {
                selection.result.current.setLiveFilters('all', DEFAULT_LIVE_TRAFFIC_FILTERS)
                clearLiveWorldShare()
            })
        }
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
        expect(view.queryByTestId('live-map-loading')).toBeNull()
        expect(view.queryByTestId('live-activity-loading')).toBeNull()
        expect(view.queryByTestId('live-paused-banner')).toBeNull()
        view.unmount()
    })

    test.each([
        { chrome: 'tab', reading: true },
        { chrome: 'tab', reading: false },
        { chrome: 'stack', reading: true },
        { chrome: 'stack', reading: false },
    ] as const)('retains values with a loading indicator in $chrome while reading=$reading', ({ chrome, reading }) => {
        mockFeed = { ...feed(), reading, pulling: reading }
        const view = render(screen(chrome))
        expect(view.getByText('Home')).toBeTruthy()
        if (chrome === 'tab') {
            expect(useTabHeaderStore.getState().slots.live?.refreshing).toBe(reading)
        } else {
            expect(view.getByLabelText('Live data').props.accessibilityState.busy).toBe(reading)
        }
        expect(view.queryByTestId('live-refreshing')).toBeNull()
        expect(view.getByTestId('live-scroll').props.refreshControl.props.refreshing).toBe(false)
        expect(view.queryByText('Updating…')).toBeNull()
        expect(view.getByTestId('live-stat-users-online-loading')).toBeTruthy()
        expect(view.queryByText("Couldn't load this yet. Live tries again every 30 seconds.")).toBeNull()
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
        expect(view.getByTestId('live-stat-screenviews-loading')).toBeTruthy()
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
        expect(view.getByTestId('live-stat-dau-loading')).toBeTruthy()
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

    test('publishes Live filters to the shared header', () => {
        mockFeed = feed()
        const view = render(screen())
        expect(useTabHeaderStore.getState().slots.live?.filter?.count).toBe(0)
        expect(view.queryByTestId('live-pause')).toBeNull()
        expect(view.queryByTestId('live-filter-button')).toBeNull()
        expect(
            view.queryByText('Users online covers the whole project. Other metrics show mobile activity.')
        ).toBeNull()
        view.unmount()
    })
})
