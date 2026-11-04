import { Stack, useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { View } from 'react-native'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { AnimatedLogomark } from '@/ui/icons/AnimatedLogomark'
import { useOverlayDismiss } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import type { TabHeaderSlot, TabKey } from './tabHeaderStore'

const TITLES: Record<TabKey, string> = {
    inbox: 'Inbox',
    chats: 'Chats',
    views: 'Views',
    errors: 'Errors',
    replay: 'Sessions',
}

export function NativeTabChrome({
    tab,
    slot,
    onMore,
}: {
    tab: TabKey
    slot: TabHeaderSlot | null
    onMore: () => void
}): ReactElement {
    const colors = useColors()
    const dismiss = useOverlayDismiss()
    const router = useRouter()
    return (
        <>
            <Stack.Screen
                options={{
                    headerShown: true,
                    gestureEnabled: !dismiss,
                    headerTransparent: true,
                    headerStyle: { backgroundColor: colors.background },
                    headerLargeStyle: { backgroundColor: colors.background },
                    headerTitle: dismiss
                        ? ''
                        : (slot?.editing?.title ??
                          (slot?.hint || slot?.status ? `${TITLES[tab]} · ${slot.hint ?? slot.status}` : TITLES[tab])),
                    headerTintColor: colors.ink,
                    headerTitleStyle: type.screenTitle,
                    headerShadowVisible: false,
                    scrollEdgeEffects: { top: 'hidden' },
                    headerBackVisible: false,
                }}
            />
            <Stack.Toolbar placement="left">
                <Stack.Toolbar.View hidesSharedBackground hidden={!!dismiss}>
                    <View
                        accessible
                        accessibilityRole="image"
                        accessibilityLabel="PostHog"
                        accessibilityState={{ busy: slot?.refreshing ?? false }}
                        testID="tabs-logomark"
                        style={{ width: (18 * 52) / 28, height: 44, justifyContent: 'center' }}
                    >
                        <AnimatedLogomark height={18} animate={slot?.refreshing ?? false} />
                    </View>
                </Stack.Toolbar.View>
            </Stack.Toolbar>
            <Stack.Toolbar placement="right">
                {dismiss ? <Stack.Toolbar.Button icon="xmark" accessibilityLabel="Close" onPress={dismiss} /> : null}
                {!dismiss && slot?.editing ? (
                    <Stack.Toolbar.Button onPress={slot.editing.onDone} variant="done">
                        Done
                    </Stack.Toolbar.Button>
                ) : null}
                {!dismiss && !slot?.editing && slot?.filter ? (
                    <Stack.Toolbar.Button
                        icon="line.3.horizontal.decrease"
                        accessibilityLabel="Filter and sort"
                        selected={slot.filter.active}
                        onPress={slot.filter.onPress}
                    />
                ) : null}
                {!dismiss && !slot?.editing ? (
                    <Stack.Toolbar.Button
                        icon="square.and.pencil"
                        accessibilityLabel="Chat"
                        onPress={() =>
                            router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } })
                        }
                    />
                ) : null}
                {!dismiss && !slot?.editing ? (
                    <Stack.Toolbar.Button icon="ellipsis" accessibilityLabel="More" onPress={onMore} />
                ) : null}
            </Stack.Toolbar>
        </>
    )
}
