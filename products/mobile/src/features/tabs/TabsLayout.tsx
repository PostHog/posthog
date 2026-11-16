import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect, useLayoutEffect } from 'react'
import { Platform, View } from 'react-native'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { useToasts } from '@/features/views/ViewsToast'
import { track } from '@/lib/analytics'
import { NAV_RAIL_WIDTH } from '@/ui/adaptiveLayout'
import { MobileScene } from '@/ui/MobileScene'
import { OverlayHost, OverlayPortal } from '@/ui/OverlayPortal'
import { SceneFrame } from '@/ui/SceneFrame'
import { useColors } from '@/ui/theme'
import { useAppLayout } from '@/ui/useAppLayout'
import { NativeTabsLayout } from './NativeTabsLayout'
import { NavToastsContext } from './navToasts'
import { TabsChrome } from './TabsChrome'
import { TabsNavigation } from './TabsNavigation'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'
import { tabForRoute, tabRouteName } from './tabRoutes'

function TabBar({ state, navigateToTab }: BottomTabBarProps): ReactElement {
    const focused = state.routes[state.index]?.name
    const goTo = (tab: TabKey): void => {
        const key = state.routes.find((item) => item.name === tabRouteName(tab))?.key
        if (key) navigateToTab(key)
    }

    // A layout effect, so the header shows the new tab's title in the same frame as the new scene.
    const tab = tabForRoute(focused)
    useLayoutEffect(() => {
        useTabHeaderStore.getState().setFocused(tab)
    }, [tab])

    // The bar stays mounted across tab switches, so it counts each open once, unlike a focus effect in the screen,
    // which also fires when a pushed report, Settings or the chat sheet closes. The pinned lists count their own opens,
    // because the same screens also open pushed from Views.
    useEffect(() => {
        if (tab === 'chats') {
            track('mobile_chats_opened')
        } else if (tab === 'inbox') {
            track('mobile_inbox_opened')
        }
    }, [tab])
    useViewsOpenedEvent(focused === 'views')

    return (
        <OverlayPortal>
            <TabsNavigation tab={tab} onNavigate={goTo} />
        </OverlayPortal>
    )
}

function renderTabBar(props: BottomTabBarProps): ReactElement {
    return <TabBar {...props} />
}

// BottomBar and TabsHeader are absolutely positioned, so the navigator lays the scenes out full height and the lists
// pad under both. The bar and the header draw after the scenes, so screen menus and sheets go through the host to draw
// above them. The header has no zIndex for the same reason: drawing order alone puts it between the two.
function CustomTabsLayout(): ReactElement {
    const colors = useColors()
    const { rail, railSide } = useAppLayout()
    return (
        <OverlayHost>
            <View
                style={{
                    flex: 1,
                    paddingLeft: rail && railSide === 'left' ? NAV_RAIL_WIDTH : 0,
                    paddingRight: rail && railSide === 'right' ? NAV_RAIL_WIDTH : 0,
                }}
            >
                <SceneFrame>
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
                        {/* Always registered; the bar shows a slot only for a pinned list. */}
                        <Tabs.Screen name="errors" />
                        <Tabs.Screen name="replay" />
                        <Tabs.Screen name="web-analytics" />
                        <Tabs.Screen name="live" />
                    </Tabs>
                    <TabsChrome />
                </SceneFrame>
            </View>
        </OverlayHost>
    )
}

export function TabsLayout(): ReactElement {
    const toasts = useToasts()
    return (
        <NavToastsContext.Provider value={toasts}>
            {Platform.OS === 'ios' ? (
                <NativeTabsLayout />
            ) : (
                <MobileScene>
                    <CustomTabsLayout />
                </MobileScene>
            )}
        </NavToastsContext.Provider>
    )
}
