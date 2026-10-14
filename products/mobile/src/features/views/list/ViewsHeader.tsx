import type { ReactElement, Ref } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { RefreshButton, type RefreshButtonState, RefreshHint } from '@/ui/RefreshButton'
import { colors, layout, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

const HEADER_TOP = 62
const TITLE_HEIGHT = type.screenTitle.lineHeight ?? 39
const STATUS_HEIGHT = 18
const HEADER_ROW_BOTTOM = HEADER_TOP + TITLE_HEIGHT + STATUS_HEIGHT
/** Design-frame offset where the list content starts at rest. The refresh hint sits in the gap above it. */
export const VIEWS_HEADER_BOTTOM = HEADER_ROW_BOTTOM + 23
/** The fade below the row reaches past the first row's top, so rows dissolve under the header instead of being cut. */
const HEADER_FADE = 24
const HEADER_SOLID = HEADER_ROW_BOTTOM / (HEADER_ROW_BOTTOM + HEADER_FADE)

interface RefreshProps {
    state: RefreshButtonState
    onPress: () => void
    blockedLabel: string
    hint: string | null
}

interface ViewsHeaderProps {
    /** Edit pins replaces the title, the status line and the buttons. */
    editing: boolean
    /** Null hides the line. */
    status: string | null
    refresh: RefreshProps | null
    onMore: () => void
    onDone: () => void
    /** The More button, for anchoring the overflow menu. */
    moreRef?: Ref<View>
}

export function ViewsHeader({ editing, status, refresh, onMore, onDone, moreRef }: ViewsHeaderProps): ReactElement {
    const insets = useScreenInsets()
    const line = editing ? 'Changes save as you go' : status
    return (
        <View style={[styles.header, { paddingTop: topOffset(insets, HEADER_TOP) }]}>
            <BlurEdge solid={HEADER_SOLID} />
            <FadeEdge direction="down" solid={HEADER_SOLID} opacity={layout.chromeTint} />
            <View style={styles.titleStack}>
                <View style={styles.titleGroup}>
                    <PostHogLogomark height={18} />
                    <Text style={styles.title} accessibilityRole="header">
                        {editing ? 'Edit pins' : 'Views'}
                    </Text>
                </View>
                <Text
                    style={styles.status}
                    numberOfLines={1}
                    accessibilityRole="text"
                    testID={line ? 'views-updated' : undefined}
                >
                    {line ?? ''}
                </Text>
                {!editing && refresh?.hint ? <RefreshHint text={refresh.hint} style={styles.hint} /> : null}
            </View>
            {editing ? (
                <Pressable44
                    onPress={onDone}
                    accessibilityLabel="Done"
                    pressedBackground={colors.inkHover}
                    style={styles.done}
                    testID="edit-pins-done"
                >
                    <Text style={styles.doneText}>Done</Text>
                </Pressable44>
            ) : (
                <PillControl>
                    <RefreshButton
                        state={refresh?.state ?? 'idle'}
                        onPress={refresh?.onPress ?? noop}
                        blockedLabel={refresh?.blockedLabel}
                        disabled={refresh === null}
                    />
                    <Pressable44
                        ref={moreRef}
                        onPress={onMore}
                        disabled={refresh === null}
                        accessibilityLabel="More"
                        pressedBackground={colors.background}
                        style={styles.button}
                        testID="views-menu"
                    >
                        <MoreIcon size={22} color={refresh === null ? colors.disabled : colors.ink} />
                    </Pressable44>
                </PillControl>
            )}
        </View>
    )
}

const noop = (): void => undefined

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
        gap: 10,
        paddingHorizontal: layout.inboxGutter,
        paddingBottom: HEADER_FADE,
        pointerEvents: 'box-none',
    },
    titleStack: {
        flexShrink: 1,
        minWidth: 0,
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
    status: {
        fontSize: 13,
        lineHeight: STATUS_HEIGHT,
        minHeight: STATUS_HEIGHT,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    hint: {
        position: 'absolute',
        top: '100%',
        left: 0,
        marginTop: 2,
        width: 320,
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    done: {
        height: 46,
        paddingHorizontal: 22,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    doneText: {
        ...type.button,
        color: colors.white,
    },
})
