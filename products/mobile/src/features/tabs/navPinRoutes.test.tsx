import { router, Stack } from 'expo-router'
import { Tabs } from 'expo-router/js-tabs'
import { NativeTabs } from 'expo-router/native-tabs'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { defaultPageHref } from '@/features/settings/defaultPageStore'

import { openNavTarget } from './navPinRoutes'
import { NAV_PINS, type NavPin, restoreNavPins, useNavPins } from './navPinStore'
import { tabRouteName } from './tabRoutes'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))

function TabsStub(): ReactElement {
    return (
        <Tabs>
            <Tabs.Screen name="inbox" />
            <Tabs.Screen name="views" />
            {NAV_PINS.map((pin) => (
                <Tabs.Screen key={pin} name={tabRouteName(pin)} />
            ))}
        </Tabs>
    )
}

function NativeTabsStub(): ReactElement {
    const pins = useNavPins()
    return (
        <NativeTabs>
            <NativeTabs.Trigger name="inbox" />
            <NativeTabs.Trigger name="views" />
            {NAV_PINS.map((pin) => (
                <NativeTabs.Trigger key={pin} name={tabRouteName(pin)} hidden={!pins.includes(pin)} />
            ))}
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

    // Web analytics and Live open their pushed `/views/...` screens, which carry the entry for their open event.
    const PINS: readonly { pin: NavPin; stack: string[]; params: Record<string, string> }[] = [
        { pin: 'errors', stack: ['(stack)', 'errors'], params: {} },
        { pin: 'replay', stack: ['(stack)', 'replay'], params: {} },
        { pin: 'web_analytics', stack: ['views', 'web-analytics'], params: { from: 'browse' } },
        { pin: 'live', stack: ['views', 'live'], params: { from: 'browse' } },
    ]

    test.each([
        ...PINS.map((pin) => ({ layout: 'native', TabLayout: NativeTabsStub, ...pin })),
        ...PINS.map((pin) => ({ layout: 'custom', TabLayout: TabsStub, ...pin })),
    ])(
        '$layout opens $pin above Views when unpinned and in its tab when pinned',
        async ({ TabLayout, pin, stack, params }) => {
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
                    '(tabs)/web-analytics/_layout': ListStack,
                    '(tabs)/web-analytics/index': Screen,
                    '(tabs)/live/_layout': ListStack,
                    '(tabs)/live/index': Screen,
                    '(stack)/errors/index': Screen,
                    '(stack)/replay/index': Screen,
                    'views/web-analytics/index': Screen,
                    'views/live': Screen,
                },
                { initialUrl: '/(tabs)/views' }
            )
            expect(app.getSegments()).toEqual(['(tabs)', 'views'])

            act(() => openNavTarget(router, pin, false, 'browse'))
            expect(app.getSegments()).toEqual(stack)
            expect(app.getSearchParams()).toEqual(params)

            act(() => router.back())
            expect(app.getSegments()).toEqual(['(tabs)', 'views'])

            act(() => restoreNavPins([pin]))
            act(() => openNavTarget(router, pin, true))
            expect(app.getSegments()).toEqual(['(tabs)', tabRouteName(pin)])
        }
    )

    // The pushed screens live under `/views/`, so a start page path never resolves to one of them.
    test.each([
        { page: 'web_analytics', segments: ['(tabs)', 'web-analytics'] },
        { page: 'live', segments: ['(tabs)', 'live'] },
    ] as const)('the $page start page opens its tab', async ({ page, segments }) => {
        const app = await renderRouter(
            {
                _layout: ListStack,
                '(tabs)/_layout': TabsStub,
                '(tabs)/inbox': Screen,
                '(tabs)/views': Screen,
                '(tabs)/errors/index': Screen,
                '(tabs)/replay/index': Screen,
                '(tabs)/web-analytics/_layout': ListStack,
                '(tabs)/web-analytics/index': Screen,
                '(tabs)/live/_layout': ListStack,
                '(tabs)/live/index': Screen,
                'views/web-analytics/index': Screen,
                'views/live': Screen,
            },
            { initialUrl: defaultPageHref(page) }
        )
        expect(app.getSegments()).toEqual(segments)
    })
})
