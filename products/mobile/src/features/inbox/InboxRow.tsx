import { memo, type ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { formatRelativeAgo } from '@/lib/dates'
import { sourceInfo } from '@/model/sources'
import type { InboxItem } from '@/model/types'
import { IconTile } from '@/ui/IconTile'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, type } from '@/ui/tokens'

interface InboxRowProps {
    item: InboxItem
    now: Date
    onOpen: (reportId: string) => void
}

export const InboxRow = memo(function InboxRow({ item, now, onOpen }: InboxRowProps): ReactElement {
    const { Icon } = sourceInfo(item.sourceProduct)
    const done = item.state === 'done' || item.state === 'dismissed'
    const muted = done || item.state === 'snoozed'
    const when =
        item.state === 'snoozed' && item.snoozeLabel ? item.snoozeLabel : formatRelativeAgo(item.updatedAt, now)
    return (
        <Pressable44
            onPress={() => onOpen(item.reportId)}
            pressedBackground={colors.sunken}
            style={styles.row}
            accessibilityLabel={`${item.title}, ${item.sourceLabel}, ${when}${item.needsInput ? ', needs your input' : ''}`}
            testID={`inbox-row-${item.reportId}`}
        >
            <IconTile muted={muted} needsInput={item.needsInput}>
                <Icon size={18} color={muted ? colors.tertiary : colors.ink} />
            </IconTile>
            <View style={styles.body}>
                <Text style={[styles.title, muted && styles.mutedTitle, done && styles.doneTitle]} numberOfLines={1}>
                    {item.title}
                </Text>
                <View style={styles.meta}>
                    <Text style={styles.metaText} numberOfLines={1}>
                        {item.sourceLabel}
                    </Text>
                    <View style={styles.dot} />
                    <Text style={styles.metaText} numberOfLines={1}>
                        {when}
                    </Text>
                </View>
            </View>
        </Pressable44>
    )
})

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 13,
        paddingHorizontal: 2,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    // The handoff's 44pt min-height applies to the row's content box, so the row renders 71pt tall.
    body: {
        flex: 1,
        minWidth: 0,
        minHeight: 44,
        justifyContent: 'center',
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
    mutedTitle: {
        color: colors.tertiary,
    },
    doneTitle: {
        textDecorationLine: 'line-through',
    },
    meta: {
        marginTop: 3,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    metaText: {
        ...type.meta,
        color: colors.secondary,
        flexShrink: 1,
    },
    dot: {
        width: 3,
        height: 3,
        borderRadius: 1.5,
        backgroundColor: colors.dotSeparator,
    },
})
