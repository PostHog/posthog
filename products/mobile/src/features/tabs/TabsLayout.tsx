import { useRouter } from 'expo-router'
import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect, useLayoutEffect, useMemo } from 'react'
import { Platform, View } from 'react-native'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { NAV_RAIL_WIDTH } from '@/ui/adaptiveLayout'
import { MobileScene } from '@/ui/MobileScene'
import { OverlayHost, OverlayPortal } from '@/ui/OverlayPortal'
import { SceneFrame } from '@/ui/SceneFrame'
import { useColors } from '@/ui/theme'
import { useAppLayout } from '@/ui/useAppLayout'
import { BottomBar, type BottomBarSlot } from './BottomBar'
import { NativeTabsLayout } from './NativeTabsLayout'
import { MAX_NAV_PINS, type NavPin, useNavPins } from './navPinStore'
import { TabsChrome } from './TabsChrome'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'

function tabFor(route: string | undefined): TabKey {
    return route === 'chats' || route === 'views' || route === 'errors' || route === 'replay' ? route : 'inbox'
}

function selectedSlot(tab: TabKey): BottomBarSlot {
    return tab === 'inbox' ? 'home' : tab
}

/**
 * The pinned lists, plus the focused one when it was unpinned from its own screen, so its slot stays until the person
 * leaves it and the toast's Undo has something to come back to.
 */
function visiblePins(pins: readonly NavPin[], tab: TabKey): readonly NavPin[] {
    return (tab === 'errors' || tab === 'replay') && !pins.includes(tab) ? [...pins, tab].slice(-MAX_NAV_PINS) : pins
}

function TabBar({ state, navigateToTab }: BottomTabBarProps): ReactElement {
    const router = useRouter()
    const focused = state.routes[state.index]?.name
    const goTo = (route: TabKey): void => {
        const key = state.routes.find((item) => item.name === route)?.key
        if (key) navigateToTab(key)
    }

    // A layout effect, so the header shows the new tab's title in the same frame as the new scene.
    const tab = tabFor(focused)
    const pins = useNavPins()
    const { errors, replay } = useMobileProductFlags()
    const shownPins = useMemo(
        () => visiblePins(pins, tab).filter((pin) => (pin === 'errors' ? errors : replay)),
        [pins, tab, errors, replay]
    )
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
            <BottomBar
                selected={selectedSlot(tab)}
                pins={shownPins}
                onHome={() => goTo('inbox')}
                onChats={() => goTo('chats')}
                onViews={() => goTo('views')}
                onPin={goTo}
                onNewChat={() =>
                    router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } })
                }
            />
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
                    </Tabs>
                    <TabsChrome />
                </SceneFrame>
            </View>
        </OverlayHost>
    )
}

export function TabsLayout(): ReactElement {
    return Platform.OS === 'ios' ? (
        <NativeTabsLayout />
    ) : (
        <MobileScene>
            <CustomTabsLayout />
        </MobileScene>
    )
}
