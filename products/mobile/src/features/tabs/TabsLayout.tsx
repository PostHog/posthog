import { useRouter } from 'expo-router'
import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { Linking, View } from 'react-native'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useViewer } from '@/auth/useViewer'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { usePostHogStatus } from '@/features/status/usePostHogStatus'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { navListWebUrl } from '@/features/views/webLinks'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { safeHttpsUrl } from '@/lib/urls'
import { NAV_RAIL_WIDTH } from '@/ui/adaptiveLayout'
import { OverlayHost, OverlayPortal } from '@/ui/OverlayPortal'
import { SceneFrame } from '@/ui/SceneFrame'
import { useColors } from '@/ui/theme'
import { useAppLayout } from '@/ui/useAppLayout'

import { useExitDemo, useSignOutAction } from '../settings/useSignOut'
import { BottomBar, type BottomBarSlot } from './BottomBar'
import { NavMenu } from './NavMenu'
import { changeNavPin } from './navPinActions'
import { MAX_NAV_PINS, type NavPin, useNavPins } from './navPinStore'
import { TabsHeader } from './TabsHeader'
import { type TabKey, useFocusedTabHeader, useTabHeaderStore } from './tabHeaderStore'

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

function TabBar({ state, navigation }: BottomTabBarProps): ReactElement {
    const router = useRouter()
    const focused = state.routes[state.index]?.name
    const goTo = (route: TabKey): void => {
        navigation.navigate(route)
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

function TabsChrome(): ReactElement {
    const router = useRouter()
    const viewer = useViewer()
    const { tab, slot } = useFocusedTabHeader()
    const signedIn = useAuthStore((state) => state.signedIn)
    const exitDemo = useExitDemo()
    const signOut = useSignOutAction()
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmingSignOut, setConfirmingSignOut] = useState(false)
    const scope = useProjectScope()
    const status = usePostHogStatus(scope?.host)
    // The pinned list's tab has no menu of its own, so its Unpin toast draws from here, inside the tabs' overlay host.
    const toasts = useToasts()

    const closeMenu = (): void => {
        if (signOut.pending) {
            return
        }
        setMenuOpen(false)
        setConfirmingSignOut(false)
    }
    const startSignOut = (): void => {
        if (signedIn) {
            setConfirmingSignOut(true)
            return
        }
        setMenuOpen(false)
        exitDemo()
    }
    const editPins = slot?.editPins ?? null
    const pins = useNavPins()
    const productFlags = useMobileProductFlags()
    // A list unpinned from its own tab keeps its slot until the person leaves, but no longer offers Unpin.
    const list = (tab === 'errors' || tab === 'replay') && productFlags[tab] && pins.includes(tab) ? tab : null
    const listUrl = list ? navListWebUrl(scope, list) : undefined
    const webUrl = listUrl ? safeHttpsUrl(listUrl) : undefined
    const navList = list && {
        onUnpin: () => {
            setMenuOpen(false)
            changeNavPin(list, false, 'list_menu', toasts.show)
        },
        onOpenWeb: webUrl
            ? () => {
                  setMenuOpen(false)
                  track('mobile_nav_tab_web_opened', { tab: list })
                  Linking.openURL(webUrl).catch(() => undefined)
              }
            : null,
    }

    return (
        <>
            <TabsHeader tab={tab} slot={slot} status={status} onMore={() => setMenuOpen(true)} />
            <NavMenu
                visible={menuOpen}
                projectName={viewer.projectName}
                status={status}
                onOpenStatus={() => {
                    closeMenu()
                    Linking.openURL(status.pageUrl).catch(() => toasts.show("Couldn't open PostHog status."))
                }}
                navList={navList}
                editPins={
                    editPins && {
                        disabled: editPins.disabled,
                        onPress: () => {
                            setMenuOpen(false)
                            editPins.onPress()
                        },
                    }
                }
                onClose={closeMenu}
                onSettings={() => {
                    setMenuOpen(false)
                    router.push('/settings')
                }}
                onSignOut={startSignOut}
                confirmingSignOut={confirmingSignOut}
                signOutPending={signOut.pending}
                signOutError={signOut.error}
                onCancelSignOut={() => {
                    signOut.clearError()
                    setConfirmingSignOut(false)
                }}
                onConfirmSignOut={() => void signOut.run()}
            />
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} />
        </>
    )
}

// BottomBar and TabsHeader are absolutely positioned, so the navigator lays the scenes out full height and the lists
// pad under both. The bar and the header draw after the scenes, so screen menus and sheets go through the host to draw
// above them. The header has no zIndex for the same reason: drawing order alone puts it between the two.
export function TabsLayout(): ReactElement {
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
