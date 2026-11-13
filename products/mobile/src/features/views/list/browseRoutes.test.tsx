import { router, Stack } from 'expo-router'
import { Tabs } from 'expo-router/js-tabs'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { openBrowseEntry } from './browseRoutes'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))

function TabsStub(): ReactElement {
    return (
        <Tabs>
            <Tabs.Screen name="live" />
            <Tabs.Screen name="views" />
        </Tabs>
    )
}

function ListStack(): ReactElement {
    return <Stack screenOptions={{ headerShown: false }} />
}

function Screen(): ReactElement {
    return <View />
}

describe('openBrowseEntry', () => {
    test('switches the Live row to the Home tab instead of pushing a second Live screen', async () => {
        const app = await renderRouter(
            {
                _layout: ListStack,
                '(tabs)/_layout': TabsStub,
                '(tabs)/live/_layout': ListStack,
                '(tabs)/live/index': Screen,
                '(tabs)/views': Screen,
                'views/live': Screen,
            },
            { initialUrl: '/(tabs)/views' }
        )

        act(() => openBrowseEntry(router, 'live', () => false))

        expect(app.getSegments()).toEqual(['(tabs)', 'live'])
    })
})
