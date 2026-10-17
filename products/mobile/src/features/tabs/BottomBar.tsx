import type { ComponentType, ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { HomeIcon } from '@/ui/icons/HomeIcon'
import { SpacesIcon } from '@/ui/icons/SpacesIcon'
import type { IconProps } from '@/ui/icons/types'
import { ViewsIcon } from '@/ui/icons/ViewsIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, layout, radii, shadows, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

interface BottomBarProps {
    selected: 'home' | 'chats' | 'views'
    onHome: () => void
    onChats: () => void
    onViews: () => void
    onNewChat: () => void
}

interface NavSlotProps {
    label: string
    Icon: ComponentType<IconProps>
    onPress: () => void
    disabled?: boolean
    testID: string
}

function NavSlot({ label, Icon, onPress, disabled = false, testID }: NavSlotProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityState={{ selected: false, disabled }}
            pressedBackground={colors.background}
            style={[styles.slot, disabled && styles.slotDisabled]}
            haptic="selection"
            testID={testID}
        >
            <Icon size={iconSizes.navigation} />
        </Pressable44>
    )
}

interface SelectedSlotProps {
    label: string
    Icon: ComponentType<IconProps>
    testID: string
}

function SelectedSlot({ label, Icon, testID }: SelectedSlotProps): ReactElement {
    return (
        <View
            style={[styles.slot, styles.slotSelected]}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityState={{ selected: true }}
            testID={testID}
        >
            <Icon size={iconSizes.navigation} />
        </View>
    )
}

export function BottomBar({ selected, onHome, onChats, onViews, onNewChat }: BottomBarProps): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 34) }]}>
            <BlurEdge direction="up" solid={0.6} />
            <FadeEdge direction="up" solid={0.6} opacity={layout.chromeTint} />
            <View style={[styles.nav, shadows.floatingBar]} accessibilityRole="tablist">
                {selected === 'home' ? (
                    <SelectedSlot label="Home" Icon={HomeIcon} testID="inbox-nav-home" />
                ) : (
                    <NavSlot label="Home" Icon={HomeIcon} onPress={onHome} testID="inbox-nav-home" />
                )}
                {/* The testID keeps its old name because the Argent flows select this slot by it. */}
                {selected === 'chats' ? (
                    <SelectedSlot label="Chats" Icon={SpacesIcon} testID="inbox-nav-chat" />
                ) : (
                    <NavSlot label="Chats" Icon={SpacesIcon} onPress={onChats} testID="inbox-nav-chat" />
                )}
                {selected === 'views' ? (
                    <SelectedSlot label="Views" Icon={ViewsIcon} testID="inbox-nav-views" />
                ) : (
                    <NavSlot label="Views" Icon={ViewsIcon} onPress={onViews} testID="inbox-nav-views" />
                )}
            </View>
            <Pressable44
                onPress={onNewChat}
                accessibilityLabel="Chat"
                pressedBackground={colors.inkHover}
                style={[styles.chat, shadows.fab]}
                haptic="selection"
                testID="inbox-chat"
            >
                <ComposeIcon size={iconSizes.navigation} color={colors.white} />
                <Text style={styles.chatText}>Chat</Text>
            </Pressable44>
        </View>
    )
}

const styles = StyleSheet.create({
    bar: {
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        paddingTop: 28,
        paddingHorizontal: 20,
        pointerEvents: 'box-none',
    },
    // 54pt content box plus 4pt padding and a 1pt border on each side.
    nav: {
        flex: 1,
        height: 64,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-around',
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
    },
    // Slots shrink below the handoff's 72pt on phones narrower than the 402pt prototype frame.
    slot: {
        flexBasis: 72,
        flexShrink: 1,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    slotSelected: {
        backgroundColor: colors.sunken,
    },
    slotDisabled: {
        opacity: 0.4,
    },
    // 54pt content box plus a 1pt border on each side.
    chat: {
        height: 56,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingLeft: 18,
        paddingRight: 20,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        borderWidth: 1,
        borderColor: colors.ink,
    },
    chatText: {
        ...type.button,
        color: colors.white,
    },
})
