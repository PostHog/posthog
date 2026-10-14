import { useRouter } from 'expo-router'
import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect } from 'react'

import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { track } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'
import { colors } from '@/ui/tokens'

import { BottomBar } from './BottomBar'

type TabRoute = 'inbox' | 'chats' | 'views'

function selectedSlot(route: string | undefined): 'home' | 'chats' | 'views' {
    return route === 'chats' || route === 'views' ? route : 'home'
}

function TabBar({ state, navigation }: BottomTabBarProps): ReactElement {
    const router = useRouter()
    const focused = state.routes[state.index]?.name
    const goTo = (route: TabRoute): void => {
        navigation.navigate(route)
    }

    // The bar stays mounted across tab switches, so it counts each open once, unlike a focus effect in the screen,
    // which also fires when a pushed report, Settings or the chat sheet closes.
    useEffect(() => {
        if (focused === 'chats') {
            track('mobile_chats_opened')
        } else if (focused !== 'views') {
            track('mobile_inbox_opened')
        }
    }, [focused])
    useViewsOpenedEvent(focused === 'views')

    return (
        <BottomBar
            selected={selectedSlot(focused)}
            onHome={() => goTo('inbox')}
            onChats={() => goTo('chats')}
            onViews={() => goTo('views')}
            onNewChat={() => router.push('/chat')}
        />
    )
}

function renderTabBar(props: BottomTabBarProps): ReactElement {
    return <TabBar {...props} />
}

// BottomBar is absolutely positioned, so the navigator lays the scenes out full height and the lists pad under it.
// The navigator draws the bar after the scenes, so screen menus and sheets go through the host to draw above it.
export function TabsLayout(): ReactElement {
    return (
        <OverlayHost>
            <Tabs
                tabBar={renderTabBar}
                backBehavior="firstRoute"
                screenOptions={{
                    headerShown: false,
                    sceneStyle: { backgroundColor: colors.background },
                }}
            >
                <Tabs.Screen name="inbox" />
                <Tabs.Screen name="chats" />
                <Tabs.Screen name="views" />
            </Tabs>
        </OverlayHost>
    )
}
