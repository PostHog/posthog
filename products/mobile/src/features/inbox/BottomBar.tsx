import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { FadeEdge } from '@/ui/FadeEdge'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { HomeIcon } from '@/ui/icons/HomeIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, shadows, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

interface BottomBarProps {
    onChat: () => void
}

export function BottomBar({ onChat }: BottomBarProps): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 34) }]}>
            <FadeEdge direction="up" solid={0.6} />
            <View style={[styles.nav, shadows.floatingBar]} accessibilityRole="tablist">
                <View
                    style={styles.slot}
                    accessibilityRole="tab"
                    accessibilityLabel="Home"
                    accessibilityState={{ selected: true }}
                >
                    <HomeIcon size={22} />
                </View>
            </View>
            <Pressable44
                onPress={onChat}
                accessibilityLabel="Chat"
                pressedBackground={colors.inkHover}
                style={[styles.chat, shadows.fab]}
                haptic="selection"
                testID="inbox-chat"
            >
                <ComposeIcon size={22} color={colors.white} />
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
        paddingHorizontal: 20,
        pointerEvents: 'box-none',
    },
    // 54pt content box plus 4pt padding and a 1pt border on each side.
    nav: {
        flex: 1,
        height: 64,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
    },
    slot: {
        width: 72,
        height: 46,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
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
        ...type.buttonLarge,
        color: colors.white,
    },
})
