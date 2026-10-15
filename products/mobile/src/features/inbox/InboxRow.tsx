import { memo, type ReactElement } from 'react'
import { type AccessibilityActionEvent, type AccessibilityActionInfo, StyleSheet, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { formatRelativeAgo } from '@/lib/dates'
import { sourceInfo } from '@/model/sources'
import type { InboxItem } from '@/model/types'
import { IconTile } from '@/ui/IconTile'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, type } from '@/ui/tokens'

import type { RowAnchor } from './contextMenuPlacement'
import { SwipeToReadRow } from './SwipeToReadRow'
import { useRowMenuTrigger } from './useRowMenuTrigger'

// A swipe is invisible to a screen reader, so the row offers the same change as a named action.
const MARK_READ_ACTION: AccessibilityActionInfo = { name: 'mark_read', label: 'Mark as read' }
const MARK_UNREAD_ACTION: AccessibilityActionInfo = { name: 'mark_unread', label: 'Mark as unread' }

interface InboxRowProps {
    item: InboxItem
    now: Date
    onOpen: (reportId: string) => void
    onLongPress: (item: InboxItem, anchor: RowAnchor) => void
    onSetRead: (reportId: string, read: boolean) => void
}

export const InboxRow = memo(function InboxRow({
    item,
    now,
    onOpen,
    onLongPress,
    onSetRead,
}: InboxRowProps): ReactElement {
    const menuTrigger = useRowMenuTrigger(item, onLongPress)
    const readAction = item.read ? MARK_UNREAD_ACTION : MARK_READ_ACTION
    const swipe = (read: boolean): void => {
        track('mobile_inbox_report_swiped', { action: read ? 'mark_read' : 'mark_unread', report_id: item.reportId })
        onSetRead(item.reportId, read)
    }
    const onAccessibilityAction = (event: AccessibilityActionEvent): void => {
        if (event.nativeEvent.actionName === readAction.name) {
            onSetRead(item.reportId, !item.read)
            return
        }
        menuTrigger.onAccessibilityAction(event)
    }
    const { Icon } = sourceInfo(item.sourceProduct)
    const done = item.state === 'done' || item.state === 'dismissed'
    const muted = done || item.state === 'snoozed'
    const when =
        item.state === 'snoozed' && item.snoozeLabel ? item.snoozeLabel : formatRelativeAgo(item.updatedAt, now)
    return (
        <SwipeToReadRow read={item.read} onMarkRead={() => swipe(true)} onMarkUnread={() => swipe(false)}>
            {(pressBlocked) => (
                <Pressable44
                    {...menuTrigger}
                    accessibilityActions={[...menuTrigger.accessibilityActions, readAction]}
                    onAccessibilityAction={onAccessibilityAction}
                    onPress={() => {
                        if (!pressBlocked()) {
                            onOpen(item.reportId)
                        }
                    }}
                    pressedBackground={colors.sunken}
                    style={styles.row}
                    accessibilityLabel={`${item.title}, ${item.sourceLabel}, ${when}${!item.read ? ', unread' : ''}${item.needsInput ? ', needs your input' : ''}`}
                    testID={`inbox-row-${item.reportId}`}
                >
                    <IconTile muted={muted} needsInput={item.needsInput}>
                        <Icon size={iconSizes.navigation} color={muted ? colors.tertiary : colors.ink} />
                    </IconTile>
                    <View style={styles.body}>
                        <Text
                            style={[styles.title, muted && styles.mutedTitle, done && styles.doneTitle]}
                            numberOfLines={1}
                        >
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
                    {!item.read ? <View style={styles.unreadDot} testID={`inbox-unread-${item.reportId}`} /> : null}
                </Pressable44>
            )}
        </SwipeToReadRow>
    )
})

const styles = StyleSheet.create({
    unreadDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.ink, marginRight: 6 },
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
