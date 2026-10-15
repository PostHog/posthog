import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, layout, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const HEADER_TOP = 64
const HEADER_ROW_HEIGHT = 54
const HEADER_ROW_BOTTOM = HEADER_TOP + HEADER_ROW_HEIGHT
/** Design-frame offset where the list content starts at rest. */
export const INBOX_HEADER_BOTTOM = HEADER_ROW_BOTTOM + 12
/** The fade below the row reaches past the first row's top, so rows dissolve under the header instead of being cut. */
const HEADER_FADE = 28
const HEADER_SOLID = HEADER_ROW_BOTTOM / (HEADER_ROW_BOTTOM + HEADER_FADE)

interface InboxHeaderProps {
    onRefresh: () => void
    refreshing: boolean
    onOpenMenu: () => void
}

export function InboxHeader({ onRefresh, refreshing, onOpenMenu }: InboxHeaderProps): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.header, { paddingTop: topOffset(insets, HEADER_TOP) }]}>
            <BlurEdge solid={HEADER_SOLID} />
            <FadeEdge direction="down" solid={HEADER_SOLID} opacity={layout.chromeTint} />
            <View style={styles.titleGroup}>
                <PostHogLogomark height={18} />
                <Text style={styles.title} accessibilityRole="header">
                    Inbox
                </Text>
            </View>
            <PillControl height={HEADER_ROW_HEIGHT}>
                <Pressable44
                    onPress={onRefresh}
                    disabled={refreshing}
                    accessibilityLabel="Refresh"
                    accessibilityState={{ busy: refreshing }}
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="inbox-refresh"
                >
                    <RefreshIcon size={iconSizes.navigation} color={refreshing ? colors.tertiary : colors.ink} />
                </Pressable44>
                <Pressable44
                    onPress={onOpenMenu}
                    accessibilityLabel="More"
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="inbox-more"
                >
                    <MoreIcon size={iconSizes.navigation} />
                </Pressable44>
            </PillControl>
        </View>
    )
}

const styles = StyleSheet.create({
    header: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: HEADER_FADE,
        pointerEvents: 'box-none',
    },
    titleGroup: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
