import { NativeTabs } from 'expo-router/native-tabs'
import type { ReactElement } from 'react'
import { track } from '@/lib/analytics'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { useNavigationOverlayStore } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'

import { useViewsOpenedEvent } from '../views/list/useViewsOpenedEvent'
import { useNavPins } from './navPinStore'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'

export function NativeTabsLayout(): ReactElement {
    const colors = useColors()
    const blocked = useNavigationOverlayStore((state) => state.keys.length > 0)
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const focused = useTabHeaderStore((state) => state.focused)
    useViewsOpenedEvent(focused === 'views')
    return (
        <NativeTabs
            tintColor={colors.ink}
            preferredPlacement="tabBar"
            screenListeners={({ route }) => ({
                focus: () => {
                    const tab = route.name as TabKey
                    useTabHeaderStore.getState().setFocused(tab)
                    if (tab === 'inbox') track('mobile_inbox_opened')
                    if (tab === 'chats') track('mobile_chats_opened')
                },
            })}
        >
            <NativeTabs.Trigger disabled={blocked} name="inbox" testID="inbox-nav-home" disableAutomaticContentInsets>
                <NativeTabs.Trigger.Icon sf="house" />
                <NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label>
            </NativeTabs.Trigger>
            <NativeTabs.Trigger disabled={blocked} name="chats" testID="inbox-nav-chat" disableAutomaticContentInsets>
                <NativeTabs.Trigger.Icon sf="bubble.left.and.bubble.right" />
                <NativeTabs.Trigger.Label>Chats</NativeTabs.Trigger.Label>
            </NativeTabs.Trigger>
            <NativeTabs.Trigger disabled={blocked} name="views" testID="inbox-nav-views" disableAutomaticContentInsets>
                <NativeTabs.Trigger.Icon sf="square.grid.2x2" />
                <NativeTabs.Trigger.Label>Views</NativeTabs.Trigger.Label>
            </NativeTabs.Trigger>
            <NativeTabs.Trigger
                disabled={blocked}
                name="errors"
                testID="nav-pin-errors"
                hidden={!flags.errors || (!pins.includes('errors') && focused !== 'errors')}
                disableAutomaticContentInsets
            >
                <NativeTabs.Trigger.Icon sf="exclamationmark.triangle" />
                <NativeTabs.Trigger.Label>Errors</NativeTabs.Trigger.Label>
            </NativeTabs.Trigger>
            <NativeTabs.Trigger
                disabled={blocked}
                name="replay"
                testID="nav-pin-replay"
                hidden={!flags.replay || (!pins.includes('replay') && focused !== 'replay')}
                disableAutomaticContentInsets
            >
                <NativeTabs.Trigger.Icon sf="play.rectangle" />
                <NativeTabs.Trigger.Label>Sessions</NativeTabs.Trigger.Label>
            </NativeTabs.Trigger>
        </NativeTabs>
    )
}
