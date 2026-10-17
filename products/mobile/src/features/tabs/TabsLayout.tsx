import { useRouter } from 'expo-router'
import { type BottomTabBarProps, Tabs } from 'expo-router/js-tabs'
import { type ReactElement, useEffect, useLayoutEffect, useState } from 'react'
import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { track } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'
import { colors } from '@/ui/tokens'

import { useExitDemo, useSignOutAction } from '../settings/useSignOut'
import { BottomBar } from './BottomBar'
import { NavMenu } from './NavMenu'
import { TabsHeader } from './TabsHeader'
import { type TabKey, useFocusedTabHeader, useTabHeaderStore } from './tabHeaderStore'

function tabFor(route: string | undefined): TabKey {
    return route === 'chats' || route === 'views' ? route : 'inbox'
}

function selectedSlot(tab: TabKey): 'home' | 'chats' | 'views' {
    return tab === 'inbox' ? 'home' : tab
}

function TabBar({ state, navigation }: BottomTabBarProps): ReactElement {
    const router = useRouter()
    const focused = state.routes[state.index]?.name
    const goTo = (route: TabKey): void => {
        navigation.navigate(route)
    }

    // A layout effect, so the header shows the new tab's title in the same frame as the new scene.
    const tab = tabFor(focused)
    useLayoutEffect(() => {
        useTabHeaderStore.getState().setFocused(tab)
    }, [tab])

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
            selected={selectedSlot(tab)}
            onHome={() => goTo('inbox')}
            onChats={() => goTo('chats')}
            onViews={() => goTo('views')}
            onNewChat={() => router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } })}
        />
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

    return (
        <>
            <TabsHeader tab={tab} slot={slot} onMore={() => setMenuOpen(true)} />
            <NavMenu
                visible={menuOpen}
                projectName={viewer.projectName}
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
        </>
    )
}

// BottomBar and TabsHeader are absolutely positioned, so the navigator lays the scenes out full height and the lists
// pad under both. The bar and the header draw after the scenes, so screen menus and sheets go through the host to draw
// above them. The header has no zIndex for the same reason: drawing order alone puts it between the two.
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
            <TabsChrome />
        </OverlayHost>
    )
}
