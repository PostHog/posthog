import { NativeTabs } from 'expo-router/native-tabs'
import { type ReactElement, useRef } from 'react'
import { useViewsOpenedEvent } from '@/features/views/list/useViewsOpenedEvent'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { useNavigationOverlayStore } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'
import { useNativeRail } from '@/ui/useNativeRail'
import { useNavPins } from './navPinStore'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'
import { visibleNavPins } from './visibleNavPins'

const LABELS: Record<TabKey, string> = {
    inbox: 'Home',
    chats: 'Chats',
    views: 'Views',
    errors: 'Errors',
    replay: 'Sessions',
}
const ICONS = {
    inbox: nativeIcons.home,
    chats: nativeIcons.chats,
    views: nativeIcons.views,
    errors: nativeIcons.errors,
    replay: nativeIcons.replay,
}
const TEST_IDS = {
    inbox: 'inbox-nav-home',
    chats: 'inbox-nav-chat',
    views: 'inbox-nav-views',
    errors: 'nav-pin-errors',
    replay: 'nav-pin-replay',
}

export function NativeTabsLayout(): ReactElement {
    const colors = useColors()
    const nativeRail = useNativeRail()
    const blocked = useNavigationOverlayStore((state) => state.keys.length > 0)
    const lastFocused = useRef<TabKey | null>(null)
    const focused = useTabHeaderStore((state) => state.focused)
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const shownPins = visibleNavPins(pins, focused, flags)
    const tabs: TabKey[] = ['inbox', 'chats', 'views', ...new Set([...shownPins, 'errors', 'replay'] as const)]
    useViewsOpenedEvent(focused === 'views')
    return (
        <NativeTabs
            hidden={!nativeRail}
            disableHiddenAnimation
            tintColor={colors.ink}
            iconColor={colors.ink}
            preferredPlacement="tabBar"
            screenListeners={({ route }) => ({
                focus: () => {
                    const tab = route.name as TabKey
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
                    name={tab}
                    disabled={blocked}
                    hidden={(tab === 'errors' || tab === 'replay') && !shownPins.includes(tab)}
                    testID={TEST_IDS[tab]}
                    accessibilityLabel={LABELS[tab]}
                    disableAutomaticContentInsets
                    disablePopToTop
                >
                    <NativeTabs.Trigger.Icon src={ICONS[tab]} renderingMode="template" />
                    <NativeTabs.Trigger.Label hidden>{LABELS[tab]}</NativeTabs.Trigger.Label>
                </NativeTabs.Trigger>
            ))}
        </NativeTabs>
    )
}
