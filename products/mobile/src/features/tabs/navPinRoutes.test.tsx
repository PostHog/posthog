import { router, Stack } from 'expo-router'
import { Tabs } from 'expo-router/js-tabs'
import { NativeTabs } from 'expo-router/native-tabs'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { openNavTarget } from './navPinRoutes'
import { type NavPin, restoreNavPins, useNavPins } from './navPinStore'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))

function TabsStub(): ReactElement {
    return (
        <Tabs>
            <Tabs.Screen name="inbox" />
            <Tabs.Screen name="views" />
            <Tabs.Screen name="errors" />
            <Tabs.Screen name="replay" />
        </Tabs>
    )
}

function NativeTabsStub(): ReactElement {
    const pins = useNavPins()
    return (
        <NativeTabs>
            <NativeTabs.Trigger name="inbox" />
            <NativeTabs.Trigger name="views" />
            <NativeTabs.Trigger name="errors" hidden={!pins.includes('errors')} />
            <NativeTabs.Trigger name="replay" hidden={!pins.includes('replay')} />
        </NativeTabs>
    )
}

function ListStack(): ReactElement {
    return <Stack screenOptions={{ headerShown: false }} />
}

function Screen(): ReactElement {
    return <View />
}

describe('pinnable list navigation', () => {
    afterEach(() => act(() => restoreNavPins([])))

    test.each([
        { layout: 'native', TabLayout: NativeTabsStub, pin: 'errors' as NavPin },
        { layout: 'native', TabLayout: NativeTabsStub, pin: 'replay' as NavPin },
        { layout: 'custom', TabLayout: TabsStub, pin: 'errors' as NavPin },
        { layout: 'custom', TabLayout: TabsStub, pin: 'replay' as NavPin },
    ])('$layout opens $pin above Views when unpinned and in its tab when pinned', async ({ TabLayout, pin }) => {
        const app = await renderRouter(
            {
                _layout: ListStack,
                '(tabs)/_layout': TabLayout,
                '(tabs)/inbox': Screen,
                '(tabs)/views': Screen,
                '(tabs)/errors/_layout': ListStack,
                '(tabs)/errors/index': Screen,
                '(tabs)/replay/_layout': ListStack,
                '(tabs)/replay/index': Screen,
                '(stack)/errors/index': Screen,
                '(stack)/replay/index': Screen,
            },
            { initialUrl: '/(tabs)/views' }
        )
        expect(app.getSegments()).toEqual(['(tabs)', 'views'])

        act(() => openNavTarget(router, pin, false))
        expect(app.getSegments()).toEqual(['(stack)', pin])

        act(() => router.back())
        expect(app.getSegments()).toEqual(['(tabs)', 'views'])

        act(() => restoreNavPins([pin]))
        act(() => openNavTarget(router, pin, true))
        expect(app.getSegments()).toEqual(['(tabs)', pin])
    })
})
