import { useSegments } from 'expo-router'
import { NativeTabs } from 'expo-router/native-tabs'
import { type ReactElement, useRef } from 'react'
import { useInboxHasUnread } from '@/features/inbox/useInboxHasUnread'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { useNavigationOverlayStore } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'
import { useNativeRail } from '@/ui/useNativeRail'
import { NAV_PINS, useNavPins } from './navPinStore'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'
import { BAR_TABS, tabForRoute, tabRouteName } from './tabRoutes'
import { visibleNavPins } from './visibleNavPins'

const LABELS: Record<TabKey, string> = {
    live: 'Home',
    inbox: 'Inbox',
    chats: 'Chats',
    views: 'Views',
    errors: 'Errors',
    replay: 'Sessions',
    web_analytics: 'Web analytics',
}
const ICONS = {
    live: nativeIcons.home,
    inbox: nativeIcons.inbox,
    chats: nativeIcons.chats,
    views: nativeIcons.views,
    errors: nativeIcons.errors,
    replay: nativeIcons.replay,
    web_analytics: nativeIcons.webAnalytics,
} satisfies Record<TabKey, unknown>
const TEST_IDS: Record<TabKey, string> = {
    live: 'inbox-nav-home',
    inbox: 'nav-inbox',
    chats: 'inbox-nav-chat',
    views: 'inbox-nav-views',
    errors: 'nav-pin-errors',
    replay: 'nav-pin-replay',
    web_analytics: 'nav-pin-web_analytics',
}

export function NativeTabsLayout(): ReactElement {
    const colors = useColors()
    const nativeRail = useNativeRail()
    const blocked = useNavigationOverlayStore((state) => state.keys.length > 0)
    const lastFocused = useRef<TabKey | null>(null)
    const focused = useTabHeaderStore((state) => state.focused)
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const segments: readonly string[] = useSegments()
    const [group, route] = segments
    const inboxUnread = useInboxHasUnread()
    const shownPins = visibleNavPins(pins, group === '(tabs)' ? tabForRoute(route) : focused, flags)
    // Every pinnable tab stays registered, the shown pin first so it takes the slot after Views. Live is pinnable too,
    // but it is Home, so it keeps the first slot.
    const pinTabs = new Set([...shownPins, ...NAV_PINS].filter((pin) => !BAR_TABS.includes(pin)))
    const tabs: TabKey[] = [...BAR_TABS, ...pinTabs]
    useViewsOpenedEvent(focused === 'views')
    return (
        <NativeTabs
            hidden={!nativeRail}
            disableHiddenAnimation
            tintColor={colors.ink}
            iconColor={colors.ink}
            badgeBackgroundColor={colors.blue}
            preferredPlacement="tabBar"
            screenListeners={({ route }) => ({
                focus: () => {
                    const tab = tabForRoute(route.name)
                    useTabHeaderStore.getState().setFocused(tab)
                    if (lastFocused.current === tab) return
                    lastFocused.current = tab
                    if (tab === 'inbox') track('mobile_inbox_opened')
                    if (tab === 'chats') track('mobile_chats_opened')
                },
            })}
        >
            {tabs.map((tab) => (
                <NativeTabs.Trigger
                    key={tab}
                    name={tabRouteName(tab)}
                    disabled={blocked}
                    hidden={!BAR_TABS.includes(tab) && !shownPins.some((pin) => pin === tab)}
                    testID={TEST_IDS[tab]}
                    accessibilityLabel={LABELS[tab]}
                    disableAutomaticContentInsets
                    disablePopToTop
                >
                    <NativeTabs.Trigger.Icon src={ICONS[tab]} renderingMode="template" />
                    <NativeTabs.Trigger.Label hidden>{LABELS[tab]}</NativeTabs.Trigger.Label>
                    {tab === 'inbox' && inboxUnread ? <NativeTabs.Trigger.Badge /> : null}
                </NativeTabs.Trigger>
            ))}
        </NativeTabs>
    )
}
