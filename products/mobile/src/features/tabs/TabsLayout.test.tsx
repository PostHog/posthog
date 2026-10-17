import { act, fireEvent, renderRouter, screen, within } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { setAnalyticsClient } from '@/lib/analytics'
import { OverlayPortal } from '@/ui/OverlayPortal'

import { TabsLayout } from './TabsLayout'
import { type TabHeaderSlot, useTabHeader } from './tabHeaderStore'

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

const LIST_SLOT: TabHeaderSlot = {
    refresh: { state: 'idle', onPress: () => undefined },
    status: null,
    editing: null,
    editPins: null,
}

function PublishingInboxStub(): ReactElement {
    useTabHeader('inbox', LIST_SLOT)
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
    afterEach(() => {
        setAnalyticsClient(null)
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

    test('keeps one More button across tabs, and its menu offers Edit pins only on Views', () => {
        renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': PublishingInboxStub,
                '(tabs)/chats': PublishingChatsStub,
                '(tabs)/views': PublishingViewsStub,
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

        fireEvent.press(screen.getByTestId('inbox-nav-views'))

        expect(screen.getByTestId('tabs-title').props.children).toBe('Views')
        expect(screen.getByTestId('tabs-more')).toBe(more)
        expect(menuItems()).toEqual({ editPins: true, inbox: false })

        fireEvent.press(screen.getByTestId('inbox-nav-chat'))

        expect(screen.getByTestId('tabs-title').props.children).toBe('Chats')
        expect(screen.getByTestId('tabs-more')).toBe(more)
        expect(menuItems()).toEqual({ editPins: false, inbox: false })
    })

    test('draws a screen overlay outside the tab scene, so it covers the bar', () => {
        renderRouter(
            {
                '(tabs)/_layout': TabsLayout,
                '(tabs)/inbox': InboxWithMenuStub,
                '(tabs)/chats': ChatsStub,
                '(tabs)/views': ViewsStub,
            },
            { initialUrl: '/inbox' }
        )

        expect(screen.getByTestId('scene-menu')).toBeTruthy()
        expect(within(screen.getByTestId('inbox-screen')).queryByTestId('scene-menu')).toBeNull()
    })
})
