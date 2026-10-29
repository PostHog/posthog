import { act, fireEvent, renderRouter, screen, within } from 'expo-router/testing-library'
import { type ReactElement, useState } from 'react'
import { Button, Text, View } from 'react-native'

import { setAnalyticsClient } from '@/lib/analytics'
import { FEATURE_FLAGS, setFeatureFlags } from '@/lib/featureFlags'
import { OverlayPortal } from '@/ui/OverlayPortal'

import { restoreNavPins, setNavPinned, useNavPinStore } from './navPinStore'
import { TabsLayout } from './TabsLayout'
import { type TabHeaderSlot, type TabKey, useTabHeader, useTabHeaderStore } from './tabHeaderStore'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
// The router's testing library mocks Reanimated with this module after the hoisted mocks run, so the patch goes here.
jest.mock('react-native-reanimated/mock', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

function InboxStub(): ReactElement {
    return <View testID="inbox-screen" />
}

function ChatsStub(): ReactElement {
    return <View testID="chats-screen" />
}

function ViewsStub(): ReactElement {
    return <View testID="views-screen" />
}

function ErrorsStub(): ReactElement {
    return <View testID="errors-screen" />
}

function ReplayStub(): ReactElement {
    return <View testID="replay-screen" />
}

// The layout always registers the pinnable lists' tabs.
const LIST_TABS = { '(tabs)/errors': ErrorsStub, '(tabs)/replay': ReplayStub }

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
        <View testID={`${tab}-screen`}>
            <Button title="Start refresh" testID="start-refresh" onPress={() => setRefreshing(true)} />
            <Button title="Finish refresh" testID="finish-refresh" onPress={() => setRefreshing(false)} />
        </View>
    )
}

function PublishingInboxStub(): ReactElement {
    useTabHeader('inbox', { ...LIST_SLOT, filter: { active: true, onPress: () => undefined } })
    return <View testID="inbox-screen" />
}

function PublishingChatsStub(): ReactElement {
    useTabHeader('chats', LIST_SLOT)
    return <View testID="chats-screen" />
}

function PublishingViewsStub(): ReactElement {
    useTabHeader('views', {
        ...LIST_SLOT,
        status: 'Updated 2 min ago',
        editPins: { disabled: false, onPress: () => undefined },
    })
    return <View testID="views-screen" />
}

function InboxWithMenuStub(): ReactElement {
    return (
        <View testID="inbox-screen">
            <OverlayPortal>
                <Text testID="scene-menu">Menu</Text>
            </OverlayPortal>
        </View>
    )
}

describe('TabsLayout', () => {
    beforeEach(() => {
        restoreNavPins([])
        setFeatureFlags({ [FEATURE_FLAGS.errorTracking]: true, [FEATURE_FLAGS.sessionReplay]: true })
    })

    afterEach(() => {
        setAnalyticsClient(null)
        setFeatureFlags({})
    })

    test.each(['inbox', 'chats', 'views'] as const)(
        'uses the %s logo as the refresh indicator only while the focused page refreshes',
        (tab) => {
            useTabHeaderStore.setState({
                slots: { inbox: LIST_SLOT, chats: LIST_SLOT, views: LIST_SLOT, errors: null, replay: null },
            })
            renderRouter(
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

            fireEvent.press(screen.getByTestId('start-refresh'))
            expect(screen.getByTestId('tabs-logomark').props.accessibilityState.busy).toBe(true)
            expect(screen.queryByTestId(`${tab}-refresh`)).toBeNull()
            expect(screen.getByTestId('tabs-more')).toBeTruthy()

            fireEvent.press(screen.getByTestId('finish-refresh'))
            expect(screen.getByTestId('tabs-logomark').props.accessibilityState.busy).toBe(false)
        }
    )

    test.each(['errors', 'replay'] as const)('hides a saved %s pin while its release flag is off', (pin) => {
        setNavPinned(pin, true)
        setFeatureFlags({})
        renderRouter(
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

    test('switches between Inbox, Chats and Views under one bar that keeps the /inbox, /chats and /views URLs', () => {
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const router = renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        expect(router.getSegments()).toEqual(['(tabs)', 'inbox'])
        const bar = screen.getByTestId('inbox-nav-views')

        fireEvent.press(screen.getByTestId('inbox-nav-chat'))

        expect(router.getPathname()).toBe('/chats')
        expect(router.getSegments()).toEqual(['(tabs)', 'chats'])
        expect(screen.getByTestId('chats-screen')).toBeTruthy()
        expect(screen.getByTestId('inbox-nav-chat').props.accessibilityState).toEqual({ selected: true })
        expect(screen.getByTestId('inbox-nav-views')).toBe(bar)

        fireEvent.press(screen.getByTestId('inbox-nav-views'))

        expect(router.getPathname()).toBe('/views')
        expect(screen.getByTestId('views-screen')).toBeTruthy()
        expect(screen.getByTestId('inbox-nav-views').props.accessibilityState).toEqual({ selected: true })

        fireEvent.press(screen.getByTestId('inbox-nav-home'))

        expect(capture.mock.calls).toEqual([
            ['mobile_inbox_opened', undefined],
            ['mobile_chats_opened', undefined],
            ['mobile_inbox_opened', undefined],
        ])
    })

    test('keeps one More button across tabs, its menu offers Edit pins only on Views, and the filter shows only on Inbox', () => {
        renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': PublishingInboxStub,
                '(tabs)/chats': PublishingChatsStub,
                '(tabs)/views': PublishingViewsStub,
                ...LIST_TABS,
            },
            { initialUrl: '/inbox' }
        )
        const more = screen.getByTestId('tabs-more')
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
        expect(screen.getByTestId('tabs-more')).toBe(more)
        expect(menuItems()).toEqual({ editPins: true, inbox: false })
        expect(screen.queryByTestId('inbox-filter')).toBeNull()

        fireEvent.press(screen.getByTestId('inbox-nav-chat'))

        expect(screen.getByTestId('tabs-title').props.children).toBe('Chats')
        expect(screen.getByTestId('tabs-more')).toBe(more)
        expect(menuItems()).toEqual({ editPins: false, inbox: false })
        expect(screen.queryByTestId('inbox-filter')).toBeNull()
    })

    test('gives a pinned list a slot after Views, keeps it while unpinned from the tab menu, and leaves its open event to the screen', () => {
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const router = renderRouter(
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
        expect(capture.mock.calls).toEqual([
            ['mobile_inbox_opened', undefined],
            ['mobile_nav_pin_changed', { pin: 'errors', pinned: false, source: 'list_menu', replaced: false }],
        ])
    })

    test('draws a screen overlay outside the tab scene, so it covers the bar', () => {
        renderRouter(
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
