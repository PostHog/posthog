import { useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'
import { Linking } from 'react-native'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useViewer } from '@/auth/useViewer'
import { usePostHogStatus } from '@/features/status/usePostHogStatus'
import { ViewsToast } from '@/features/views/ViewsToast'
import { navListWebUrl } from '@/features/views/webLinks'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { safeHttpsUrl } from '@/lib/urls'
import { useNativeRail } from '@/ui/useNativeRail'
import { useExitDemo, useSignOutAction } from '../settings/useSignOut'
import { NativeTabChrome } from './NativeTabChrome'
import { NavMenu } from './NavMenu'
import { changeNavPin } from './navPinActions'
import { isNavPin, useNavPins } from './navPinStore'
import { useNavToasts } from './navToasts'
import { TabsHeader } from './TabsHeader'
import { useFocusedTabHeader } from './tabHeaderStore'
import { navPinEnabled } from './visibleNavPins'

export function TabsChrome(): ReactElement {
    const nativeRail = useNativeRail()
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
    // A list's tab has no menu of its own, so its pin toast draws from here, inside the tabs' overlay host.
    const toasts = useNavToasts()

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
    // An unpinned list's tab (a start page, or just unpinned) offers Pin instead of Unpin.
    const list = isNavPin(tab) && navPinEnabled(tab, productFlags) ? tab : null
    const listPinned = list !== null && pins.includes(list)
    const listUrl = list ? navListWebUrl(scope, list) : undefined
    const webUrl = listUrl ? safeHttpsUrl(listUrl) : undefined
    const navList = list && {
        pinned: listPinned,
        onTogglePin: () => {
            setMenuOpen(false)
            changeNavPin(list, !listPinned, 'list_menu', toasts.show)
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
            {nativeRail ? <NativeTabChrome slot={slot} onMore={() => setMenuOpen(true)} /> : null}
            <TabsHeader
                tab={tab}
                slot={slot}
                status={status}
                nativeRail={nativeRail}
                onMore={() => setMenuOpen(true)}
            />
            <NavMenu
                visible={menuOpen}
                projectName={viewer.projectName}
                status={status}
                onOpenStatus={() => {
                    closeMenu()
                    track('mobile_status_opened', { source: 'tabs_menu' })
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
            {tab !== 'views' ? <ViewsToast toast={toasts.toast} onHide={toasts.hide} /> : null}
        </>
    )
}
