import { fireEvent, renderRouter, screen, within } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { setAnalyticsClient } from '@/lib/analytics'
import { OverlayPortal } from '@/ui/OverlayPortal'

import { TabsLayout } from './TabsLayout'

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
