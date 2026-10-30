import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { AnimatedLogomark } from '@/ui/icons/AnimatedLogomark'
import { FilterIcon } from '@/ui/icons/FilterIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { RefreshHint } from '@/ui/RefreshHint'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import type { TabHeaderSlot, TabKey } from './tabHeaderStore'

const HEADER_TOP = 64
const HEADER_ROW_HEIGHT = 54
const HEADER_ROW_BOTTOM = HEADER_TOP + HEADER_ROW_HEIGHT
const TITLE_HEIGHT = type.screenTitle.lineHeight ?? 39
const STATUS_HEIGHT = 18
/** The title is centered in the row, so the status line starts at the title's bottom edge. */
const STATUS_TOP = (HEADER_ROW_HEIGHT + TITLE_HEIGHT) / 2
const STATUS_BOTTOM = HEADER_TOP + STATUS_TOP + STATUS_HEIGHT
/** Design-frame offset where a tab's content starts at rest, with or without a status line. */
export const TABS_HEADER_BOTTOM = HEADER_ROW_BOTTOM + 12
/** The fade below the row reaches past the first row's top, so rows dissolve under the header instead of being cut. */
const HEADER_FADE = 28
const SOLID = HEADER_ROW_BOTTOM / (HEADER_ROW_BOTTOM + HEADER_FADE)
// The chrome grows by the status line, so the line stays over the solid part and the fade starts below it.
const STATUS_PADDING = STATUS_BOTTOM - HEADER_ROW_BOTTOM + HEADER_FADE
const SOLID_WITH_STATUS = STATUS_BOTTOM / (STATUS_BOTTOM + HEADER_FADE)

const FILTER_DOT = 8

const TITLES: Record<TabKey, string> = {
    inbox: 'Inbox',
    chats: 'Chats',
    views: 'Views',
    errors: 'Errors',
    replay: 'Sessions',
}

interface TabsHeaderProps {
    tab: TabKey
    /** Null until the tab's screen publishes its header state. */
    slot: TabHeaderSlot | null
    onMore: () => void
}

/**
 * The header of the Inbox, Chats and Views tabs and the pinned lists. The tabs layout draws it once, so the logo, the title and the controls
 * keep their place and their state across a tab switch. The status line is absolutely positioned, so it never moves
 * the title row, and the refresh hint takes its place while it shows, so every tab's content starts at the same offset.
 */
export function TabsHeader({ tab, slot, onMore }: TabsHeaderProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const editing = slot?.editing ?? null
    const status = slot?.status ?? null
    const hint = editing ? null : (slot?.hint ?? null)
    const filter = slot?.filter ?? null
    const withStatus = status !== null
    const solid = withStatus ? SOLID_WITH_STATUS : SOLID
    return (
        <View
            style={[
                styles.header,
                {
                    paddingTop: topOffset(insets, HEADER_TOP),
                    paddingBottom: withStatus ? STATUS_PADDING : HEADER_FADE,
                },
            ]}
        >
            <BlurEdge solid={solid} />
            <FadeEdge direction="down" solid={solid} opacity={layout.chromeTint} />
            <View style={styles.titleStack}>
                <View style={styles.titleGroup}>
                    <View
                        accessible
                        accessibilityRole="image"
                        accessibilityLabel="PostHog"
                        accessibilityState={{ busy: slot?.refreshing ?? false }}
                        testID="tabs-logomark"
                    >
                        <AnimatedLogomark height={18} animate={slot?.refreshing ?? false} />
                    </View>
                    <Text style={styles.title} numberOfLines={1} accessibilityRole="header" testID="tabs-title">
                        {editing ? editing.title : TITLES[tab]}
                    </Text>
                </View>
                {hint ? (
                    <RefreshHint text={hint} style={styles.hint} testID={`${tab}-refresh-hint`} />
                ) : status !== null ? (
                    <Text style={styles.status} numberOfLines={1} accessibilityRole="text" testID={`${tab}-updated`}>
                        {status}
                    </Text>
                ) : null}
            </View>
            {editing ? (
                <Pressable44
                    onPress={editing.onDone}
                    accessibilityLabel="Done"
                    pressedBackground={colors.inkHover}
                    style={styles.done}
                    testID="edit-pins-done"
                >
                    <Text style={styles.doneText}>Done</Text>
                </Pressable44>
            ) : (
                <PillControl height={HEADER_ROW_HEIGHT}>
                    {filter ? (
                        <Pressable44
                            onPress={filter.onPress}
                            accessibilityLabel="Filter and sort"
                            accessibilityValue={filter.active ? { text: 'Filters on' } : undefined}
                            pressedBackground={colors.background}
                            style={styles.button}
                            testID="inbox-filter"
                        >
                            <View>
                                <FilterIcon size={22} />
                                {filter.active ? <View style={styles.filterDot} testID="inbox-filter-active" /> : null}
                            </View>
                        </Pressable44>
                    ) : null}
                    <Pressable44
                        onPress={onMore}
                        accessibilityLabel="More"
                        pressedBackground={colors.background}
                        style={styles.button}
                        testID="tabs-more"
                    >
                        <MoreIcon size={22} />
                    </Pressable44>
                </PillControl>
            )}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    header: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        paddingHorizontal: layout.inboxGutter,
        pointerEvents: 'box-none',
    },
    titleStack: {
        flex: 1,
        minWidth: 0,
        height: HEADER_ROW_HEIGHT,
    },
    titleGroup: {
        height: HEADER_ROW_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    status: {
        position: 'absolute',
        top: STATUS_TOP,
        left: 0,
        right: 0,
        fontSize: 13,
        lineHeight: STATUS_HEIGHT,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    hint: {
        position: 'absolute',
        top: STATUS_TOP + 1,
        left: 0,
        right: 0,
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    filterDot: {
        position: 'absolute',
        top: -1,
        right: -2,
        width: FILTER_DOT,
        height: FILTER_DOT,
        borderRadius: FILTER_DOT / 2,
        backgroundColor: colors.blue,
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
        color: colors.onInk,
    },
}))
