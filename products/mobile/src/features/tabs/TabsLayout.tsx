import { useRouter } from 'expo-router'
import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect } from 'react'
import { Linking } from 'react-native'

import { projectWebUrl } from '@/api/client'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'
import { colors } from '@/ui/tokens'

import { BottomBar } from './BottomBar'

type TabRoute = 'inbox' | 'chats'

// The app has no product screens, so Products opens the web app's product library for this project.
function openProducts(): void {
    const url = projectWebUrl('library')
    if (!url) {
        return
    }
    track('mobile_products_opened')
    Linking.openURL(url).catch(() => undefined)
}

function TabBar({ state, navigation }: BottomTabBarProps): ReactElement {
    const router = useRouter()
    const demo = useDemoMode((demoState) => demoState.enabled)
    const scope = useProjectScope()
    const focused = state.routes[state.index]?.name
    // Demo data has no project in the web app, and a session without a scope has no project to open.
    const productsDisabled = demo || scope === null
    const goTo = (route: TabRoute): void => {
        navigation.navigate(route)
    }

    // The bar stays mounted across tab switches, so it counts each open once, unlike a focus effect in the screen,
    // which also fires when a pushed report, Settings or the chat sheet closes.
    useEffect(() => {
        track(focused === 'chats' ? 'mobile_chats_opened' : 'mobile_inbox_opened')
    }, [focused])

    return (
        <BottomBar
            selected={focused === 'chats' ? 'chats' : 'home'}
            onHome={() => goTo('inbox')}
            onChats={() => goTo('chats')}
            onNewChat={() => router.push('/chat')}
            onProducts={openProducts}
            productsDisabled={productsDisabled}
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
            </Tabs>
        </OverlayHost>
    )
}
