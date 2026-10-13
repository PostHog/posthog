import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { FadeEdge } from '@/ui/FadeEdge'
import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { colors, layout, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const HEADER_TOP = 64
/** Matches the inbox header row, which a pill control sizes, so both lists start at the same offset. */
const HEADER_ROW_HEIGHT = 54
const HEADER_ROW_BOTTOM = HEADER_TOP + HEADER_ROW_HEIGHT
/** Design-frame offset where the list content starts at rest. */
export const CHATS_HEADER_BOTTOM = HEADER_ROW_BOTTOM + 12
/** The fade below the row reaches past the first row's top, so rows dissolve under the header instead of being cut. */
const HEADER_FADE = 28
const HEADER_SOLID = HEADER_ROW_BOTTOM / (HEADER_ROW_BOTTOM + HEADER_FADE)

export function ChatsHeader(): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.header, { paddingTop: topOffset(insets, HEADER_TOP) }]}>
            <FadeEdge direction="down" solid={HEADER_SOLID} />
            <View style={styles.titleGroup}>
                <PostHogLogomark height={18} />
                <Text style={styles.title} accessibilityRole="header">
                    Chats
                </Text>
            </View>
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
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: HEADER_FADE,
        pointerEvents: 'box-none',
    },
    titleGroup: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: HEADER_ROW_HEIGHT,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
})
