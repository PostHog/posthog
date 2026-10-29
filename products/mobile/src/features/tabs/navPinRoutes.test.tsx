import { router } from 'expo-router'
import { Tabs } from 'expo-router/js-tabs'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { openNavTarget } from './navPinRoutes'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))

function TabsStub(): ReactElement {
    return <Tabs />
}

function Screen(): ReactElement {
    return <View />
}

test('an unpinned list opens the pushed screen and a pinned one its tab, though both answer /errors', () => {
    const app = renderRouter(
        { '(tabs)/_layout': TabsStub, '(tabs)/inbox': Screen, '(tabs)/errors': Screen, 'errors/index': Screen },
        { initialUrl: '/inbox' }
    )

    act(() => openNavTarget(router, 'errors', false))
    expect(app.getSegments()).toEqual(['errors'])

    act(() => openNavTarget(router, 'errors', true))
    expect(app.getSegments()).toEqual(['(tabs)', 'errors'])
})
