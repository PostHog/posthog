import { router as navigation, Stack } from 'expo-router'
import { act, fireEvent, renderRouter, screen, within } from 'expo-router/testing-library'
import { type ReactElement, useState } from 'react'
import { Button, Dimensions, Platform, Text, View } from 'react-native'

import { ViewsToast } from '@/features/views/ViewsToast'
import { setAnalyticsClient } from '@/lib/analytics'
import { FEATURE_FLAGS, setFeatureFlags } from '@/lib/featureFlags'
import { OverlayPortal } from '@/ui/OverlayPortal'

import { changeNavPin } from './navPinActions'
import { restoreNavPins, setNavPinned, useNavPinStore } from './navPinStore'
import { useNavToasts } from './navToasts'
import { TabScene } from './TabScene'
import { TabsLayout } from './TabsLayout'
import { type TabHeaderSlot, type TabKey, useTabHeader, useTabHeaderStore } from './tabHeaderStore'

jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
// The router's testing library mocks Reanimated with this module after the hoisted mocks run, so the patch goes here.
jest.mock('react-native-reanimated/mock', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/features/status/usePostHogStatus', () => ({
    usePostHogStatus: () => ({
        pageUrl: 'https://www.posthogstatus.com/eu',
        summary: 'Elevated latency',
        indicatorColor: 'yellow',
        aiIncident: {
            status: 'monitoring',
            title: 'Elevated latency',
            url: 'https://www.posthogstatus.com/incidents/example',
        },
    }),
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

function InboxStub(): ReactElement {
    return (
        <TabScene tab="inbox">
            <View testID="inbox-screen" />
        </TabScene>
    )
}

function ChatsStub(): ReactElement {
    return (
        <TabScene tab="chats">
            <View testID="chats-screen" />
        </TabScene>
    )
}

function ViewsStub(): ReactElement {
    const toasts = useNavToasts()
    const focused = useTabHeaderStore((state) => state.focused === 'views')
    return (
        <TabScene tab="views">
            <View testID="views-screen">
                <Button title="Pin errors" onPress={() => changeNavPin('errors', true, 'views_row', toasts.show)} />
            </View>
            {focused ? <ViewsToast toast={toasts.toast} onHide={toasts.hide} /> : null}
        </TabScene>
    )
}

function ErrorsStub(): ReactElement {
    return (
        <TabScene tab="errors">
            <View testID="errors-screen" />
        </TabScene>
    )
}

function ReplayStub(): ReactElement {
    return (
        <TabScene tab="replay">
            <View testID="replay-screen" />
        </TabScene>
    )
}

function WebAnalyticsStub(): ReactElement {
    return (
        <TabScene tab="web_analytics">
            <View testID="web-analytics-screen" />
        </TabScene>
    )
}

function LiveStub(): ReactElement {
    return (
        <TabScene tab="live">
            <View testID="live-screen" />
        </TabScene>
    )
}

// The layout always registers the pinnable lists' tabs.
const LIST_TABS = {
    '(tabs)/errors': ErrorsStub,
    '(tabs)/replay': ReplayStub,
    '(tabs)/web-analytics': WebAnalyticsStub,
    '(tabs)/live': LiveStub,
}

const LIST_SLOT: TabHeaderSlot = {
    hint: null,
    status: null,
    editing: null,
    editPins: null,
    filter: null,
}

function RefreshingTabStub({ tab }: { tab: TabKey }): ReactElement {
    const [refreshing, setRefreshing] = useState(false)
    useTabHeader(tab, { ...LIST_SLOT, refreshing })
    return (
        <TabScene tab={tab}>
            <View testID={`${tab}-screen`}>
                <Button title="Start refresh" testID="start-refresh" onPress={() => setRefreshing(true)} />
                <Button title="Finish refresh" testID="finish-refresh" onPress={() => setRefreshing(false)} />
            </View>
        </TabScene>
    )
}

function PublishingInboxStub(): ReactElement {
    useTabHeader('inbox', { ...LIST_SLOT, filter: { active: true, onPress: () => undefined } })
    return (
        <TabScene tab="inbox">
            <View testID="inbox-screen" />
        </TabScene>
    )
}

function PublishingChatsStub(): ReactElement {
    useTabHeader('chats', LIST_SLOT)
    return (
        <TabScene tab="chats">
            <View testID="chats-screen" />
        </TabScene>
    )
}

function PublishingViewsStub(): ReactElement {
    useTabHeader('views', {
        ...LIST_SLOT,
        status: 'Updated 2 min ago',
        editPins: { disabled: false, onPress: () => undefined },
    })
    return (
        <TabScene tab="views">
            <View testID="views-screen" />
        </TabScene>
    )
}

function InboxWithMenuStub(): ReactElement {
    return (
        <TabScene tab="inbox">
            <View testID="inbox-screen">
                <OverlayPortal>
                    <Text testID="scene-menu">Menu</Text>
                </OverlayPortal>
            </View>
        </TabScene>
    )
}

const ORIGINAL_WINDOW = Dimensions.get('window')

describe.each(['ios', 'android'] as const)('TabsLayout (%s)', (platform) => {
    const originalPlatform = Platform.OS
    beforeAll(() => {
        Platform.OS = platform
    })
    afterAll(() => {
        Platform.OS = originalPlatform
    })
    beforeEach(() => {
        restoreNavPins([])
        setFeatureFlags({ [FEATURE_FLAGS.errorTracking]: true, [FEATURE_FLAGS.sessionReplay]: true })
    })

    afterEach(() => {
        act(() => Dimensions.set({ window: ORIGINAL_WINDOW }))
        setAnalyticsClient(null)
        setFeatureFlags({})
    })

    test('exposes the regional status update from the main menu', async () => {
        await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        const more = screen.getByTestId('tabs-more')
        expect(more.props.accessibilityValue.text).toContain('Elevated latency')
        fireEvent.press(more)
        expect(screen.getByLabelText('PostHog status: Elevated latency')).toBeTruthy()
    })

    test.each(['inbox', 'chats', 'views'] as const)(
        'uses the %s logo as the refresh indicator only while the focused page refreshes',
        async (tab) => {
            useTabHeaderStore.setState({
                slots: {
                    inbox: LIST_SLOT,
                    chats: LIST_SLOT,
                    views: LIST_SLOT,
                    errors: null,
                    replay: null,
                    web_analytics: null,
                    live: null,
                },
            })
            await renderRouter(
                {
                    '(tabs)/_layout': TabsLayout,
                    '(tabs)/inbox': (): ReactElement => <RefreshingTabStub tab="inbox" />,
                    '(tabs)/chats': (): ReactElement => <RefreshingTabStub tab="chats" />,
                    '(tabs)/views': (): ReactElement => <RefreshingTabStub tab="views" />,
                    ...LIST_TABS,
                },
                { initialUrl: `/${tab}` }
            )
            const otherTab = tab === 'inbox' ? 'chats' : 'inbox'
            act(() => useTabHeaderStore.getState().setSlot(otherTab, { ...LIST_SLOT, refreshing: true }))
            expect(screen.getByTestId('tabs-logomark').props.accessibilityState.busy).toBe(false)

            fireEvent.press(within(screen.getByTestId(`${tab}-screen`)).getByTestId('start-refresh'))
            expect(screen.getByTestId('tabs-logomark').props.accessibilityState.busy).toBe(true)
            expect(screen.queryByTestId(`${tab}-refresh`)).toBeNull()
            expect(screen.getByTestId('tabs-more')).toBeTruthy()

            fireEvent.press(within(screen.getByTestId(`${tab}-screen`)).getByTestId('finish-refresh'))
            expect(screen.getByTestId('tabs-logomark').props.accessibilityState.busy).toBe(false)
        }
    )

    test.each(['errors', 'replay'] as const)('hides a saved %s pin while its release flag is off', async (pin) => {
        setNavPinned(pin, true)
        setFeatureFlags({})
        await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        expect(screen.queryByTestId(`nav-pin-${pin}`)).toBeNull()

        const flag = pin === 'errors' ? FEATURE_FLAGS.errorTracking : FEATURE_FLAGS.sessionReplay
        act(() => setFeatureFlags({ [flag]: true }))
        expect(screen.getByTestId(`nav-pin-${pin}`)).toBeTruthy()

        act(() => setFeatureFlags({}))
        expect(screen.queryByTestId(`nav-pin-${pin}`)).toBeNull()
        expect(useNavPinStore.getState().pins).toEqual([pin])
    })

    test.each([
        { pin: 'web_analytics', route: 'web-analytics', title: 'Web analytics' },
        { pin: 'live', route: 'live', title: 'Live' },
    ] as const)('shows a saved $pin pin with no release flag and opens its tab', async ({ pin, route, title }) => {
        setNavPinned(pin, true)
        setFeatureFlags({})
        const router = await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        fireEvent.press(screen.getByTestId(`nav-pin-${pin}`))

        expect(router.getSegments()).toEqual(['(tabs)', route])
        expect(screen.getByTestId('tabs-title').props.children).toBe(title)
        expect(screen.getByTestId(`nav-pin-${pin}`).props.accessibilityState).toEqual({ selected: true })
    })

    test('offers Pin to navigation on an unpinned start page tab and pins it', async () => {
        await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/live' }
        )
        fireEvent.press(screen.getByTestId('tabs-more'))

        expect(screen.queryByTestId('nav-list-unpin')).toBeNull()
        fireEvent.press(screen.getByTestId('nav-list-pin'))

        expect(useNavPinStore.getState().pins).toEqual(['live'])
        expect(screen.getByTestId('views-toast')).toBeTruthy()
    })

    test.each([
        { pin: 'web_analytics', route: 'web-analytics' },
        { pin: 'live', route: 'live' },
    ] as const)('opens an unpinned $pin route with the initial Inbox header state', async ({ pin, route }) => {
        useTabHeaderStore.getState().setFocused('inbox')
        const router = await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: `/${route}` }
        )
        expect(router.getSegments()).toEqual(['(tabs)', route])
        expect(screen.getByTestId(`${route}-screen`)).toBeTruthy()
        expect(screen.getByTestId(`nav-pin-${pin}`).props.accessibilityState).toEqual({ selected: true })
    })

    test.each([
        { width: 402, height: 874 },
        { width: 951, height: 669 },
        { width: 669, height: 951 },
    ])('switches Inbox, Chats and Views under one bar at $width × $height', async ({ width, height }) => {
        const previous = Dimensions.get('window')
        Dimensions.set({ window: { ...previous, width, height } })
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const router = await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
                settings: () => <View testID="settings-screen" />,
                _layout: () => <Stack screenOptions={{ headerShown: false }} />,
            },
            { initialUrl: '/inbox' }
        )
        expect(router.getSegments()).toEqual(['(tabs)', 'inbox'])

        fireEvent.press(screen.getByTestId('inbox-nav-chat'))

        expect(router.getPathname()).toBe('/chats')
        expect(router.getSegments()).toEqual(['(tabs)', 'chats'])
        expect(screen.getByTestId('chats-screen')).toBeTruthy()
        expect(screen.getByTestId('inbox-nav-chat').props.accessibilityState).toEqual({ selected: true })
        expect(screen.getAllByTestId('inbox-nav-views')).toHaveLength(1)

        fireEvent.press(screen.getByTestId('inbox-nav-views'))

        expect(router.getPathname()).toBe('/views')
        expect(screen.getByTestId('views-screen')).toBeTruthy()
        expect(screen.getByTestId('inbox-nav-views').props.accessibilityState).toEqual({ selected: true })

        fireEvent.press(screen.getByTestId('inbox-nav-home'))
        act(() => navigation.push('/settings'))
        act(() => navigation.back())

        expect(capture.mock.calls).toEqual([
            ['mobile_inbox_opened', undefined],
            ['mobile_chats_opened', undefined],
            ['mobile_inbox_opened', undefined],
        ])
    })

    test('keeps one More button across tabs, its menu offers Edit pins only on Views, and the filter shows only on Inbox', async () => {
        await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': PublishingInboxStub,
                '(tabs)/chats': PublishingChatsStub,
                '(tabs)/views': PublishingViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        const menuItems = (): { editPins: boolean; inbox: boolean } => {
            fireEvent.press(screen.getByTestId('tabs-more'))
            const menu = screen.getByTestId('nav-menu')
            const items = {
                editPins: within(menu).queryByTestId('views-edit-pins') !== null,
                inbox: within(menu).queryByTestId('nav-inbox') !== null,
            }
            fireEvent.press(within(menu).getByLabelText('Close', { includeHiddenElements: true }))
            act(() => jest.runOnlyPendingTimers())
            expect(screen.queryByTestId('nav-menu')).toBeNull()
            return items
        }

        expect(menuItems()).toEqual({ editPins: false, inbox: false })
        expect(screen.getByTestId('inbox-filter')).toBeTruthy()
        expect(screen.getByTestId('inbox-filter-active')).toBeTruthy()

        fireEvent.press(screen.getByTestId('inbox-nav-views'))

        expect(screen.getByTestId('tabs-title').props.children).toBe('Views')
        expect(screen.getAllByTestId('tabs-more')).toHaveLength(1)
        expect(menuItems()).toEqual({ editPins: true, inbox: false })
        expect(screen.queryByTestId('inbox-filter')).toBeNull()

        fireEvent.press(screen.getByTestId('inbox-nav-chat'))

        expect(screen.getByTestId('tabs-title').props.children).toBe('Chats')
        expect(screen.getAllByTestId('tabs-more')).toHaveLength(1)
        expect(menuItems()).toEqual({ editPins: false, inbox: false })
        expect(screen.queryByTestId('inbox-filter')).toBeNull()
    })

    test('gives a pinned list a slot after Views, keeps it while unpinned from the tab menu, and leaves its open event to the screen', async () => {
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const router = await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        expect(screen.queryByTestId('nav-pin-errors')).toBeNull()

        act(() => setNavPinned('errors', true))
        fireEvent.press(screen.getByTestId('nav-pin-errors'))

        expect(router.getSegments()).toEqual(['(tabs)', 'errors'])
        expect(screen.getByTestId('tabs-title').props.children).toBe('Errors')
        expect(screen.getByTestId('nav-pin-errors').props.accessibilityState).toEqual({ selected: true })

        fireEvent.press(screen.getByTestId('tabs-more'))
        fireEvent.press(screen.getByTestId('nav-list-unpin'))

        expect(screen.getByTestId('views-toast')).toBeTruthy()
        expect(screen.getByTestId('nav-pin-errors')).toBeTruthy()

        fireEvent.press(screen.getByTestId('inbox-nav-views'))

        expect(screen.queryByTestId('nav-pin-errors')).toBeNull()
        fireEvent.press(screen.getByTestId('views-toast-undo'))
        expect(useNavPinStore.getState().pins).toEqual(['errors'])
        expect(capture.mock.calls).toEqual([
            ['mobile_inbox_opened', undefined],
            ['mobile_nav_pin_changed', { pin: 'errors', pinned: false, source: 'list_menu', replaced: false }],
            ['mobile_nav_pin_changed', { pin: 'errors', pinned: true, source: 'undo', replaced: false }],
        ])
    })

    test('keeps the separate Chat button opening compose from the inbox', async () => {
        const router = await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                chat: ChatsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )

        fireEvent.press(screen.getByTestId('inbox-chat'))

        expect(router.getPathname()).toBe('/chat')
        expect(router.getSearchParams()).toMatchObject({ entry: 'compose' })
    })

    test('draws a screen overlay outside the tab scene, so it covers the bar', async () => {
        await renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxWithMenuStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )

        expect(screen.getByTestId('scene-menu')).toBeTruthy()
        expect(within(screen.getByTestId('inbox-screen')).queryByTestId('scene-menu')).toBeNull()
    })
})
