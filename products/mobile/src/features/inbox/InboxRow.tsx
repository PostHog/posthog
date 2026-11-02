import { memo, type ReactElement } from 'react'
import { type AccessibilityActionEvent, type AccessibilityActionInfo, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { formatRelativeAgo } from '@/lib/dates'
import { pullRequestNumber } from '@/model/adapters/report'
import { sourceInfo } from '@/model/sources'
import type { InboxItem, PullRequestView } from '@/model/types'
import { IconTile } from '@/ui/IconTile'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { RowAnchor } from './contextMenuPlacement'
import { SwipeToReadRow } from './SwipeToReadRow'
import { useRowMenuTrigger } from './useRowMenuTrigger'

// A swipe is invisible to a screen reader, so the row offers the same change as a named action.
const MARK_READ_ACTION: AccessibilityActionInfo = { name: 'mark_read', label: 'Mark as read' }
const MARK_UNREAD_ACTION: AccessibilityActionInfo = { name: 'mark_unread', label: 'Mark as unread' }
const PR_ICON_SIZE = 11

interface BadgeColors {
    text: string
    border: string
}

// Matches the web inbox: green for open, purple for merged, gray for draft, closed and unknown.
function prStateColors(colors: ThemeColors): Partial<Record<PullRequestView['state'], BadgeColors>> {
    return {
        open: { text: colors.diffGreen, border: colors.diffGreenBorder },
        merged: { text: colors.purple, border: colors.purpleBorder },
    }
}
const PR_STATE_LABELS: Partial<Record<PullRequestView['state'], string>> = {
    open: 'open',
    merged: 'merged',
}

function badgeColors(state: PullRequestView['state'] | undefined, muted: boolean, colors: ThemeColors): BadgeColors {
    const stateColors = muted || !state ? undefined : prStateColors(colors)[state]
    if (stateColors) {
        return stateColors
    }
    return { text: muted ? colors.tertiary : colors.secondary, border: colors.border }
}

function prLabel(prNumber: number | undefined, state: PullRequestView['state'] | undefined): string {
    if (prNumber === undefined) {
        return ''
    }
    const stateWord = state ? PR_STATE_LABELS[state] : undefined
    return `, PR #${prNumber}${stateWord ? ` ${stateWord}` : ''}`
}

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
    const styles = useStyles()
    const colors = useColors()
    const menuTrigger = useRowMenuTrigger(item, onLongPress)
    const readAction = item.read ? MARK_UNREAD_ACTION : MARK_READ_ACTION
    const swipe = (read: boolean): void => {
        track('mobile_inbox_report_swiped', { action: read ? 'mark_read' : 'mark_unread', report_id: item.reportId })
        if (read !== item.read) {
            onSetRead(item.reportId, read)
        }
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
    const prNumber = item.pullRequestUrl ? pullRequestNumber(item.pullRequestUrl) : undefined
    const badge = badgeColors(item.pullRequestState, muted, colors)
    return (
        <SwipeToReadRow onMarkRead={() => swipe(true)} onMarkUnread={() => swipe(false)}>
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
                    accessibilityLabel={`${item.title}, ${item.sourceLabel}${prLabel(prNumber, item.pullRequestState)}, ${when}${!item.read ? ', unread' : ''}${item.needsInput ? ', needs your input' : ''}`}
                    testID={`inbox-row-${item.reportId}`}
                >
                    <IconTile muted={muted}>
                        <Icon size={iconSizes.navigation} color={muted ? colors.tertiary : colors.ink} />
                    </IconTile>
                    <View style={styles.body}>
                        <Text
                            style={[
                                styles.title,
                                !item.read && styles.unreadTitle,
                                muted && styles.mutedTitle,
                                done && styles.doneTitle,
                            ]}
                            numberOfLines={1}
                        >
                            {item.title}
                        </Text>
                        <View style={styles.meta}>
                            <Text style={styles.metaText} numberOfLines={1}>
                                {item.sourceLabel}
                            </Text>
                            <View style={styles.dot} />
                            {prNumber === undefined ? null : (
                                <>
                                    <View
                                        style={[styles.prBadge, { borderColor: badge.border }]}
                                        testID={`inbox-pr-${item.reportId}`}
                                    >
                                        <GitBranchIcon size={PR_ICON_SIZE} strokeWidth={2} color={badge.text} />
                                        <Text style={[styles.prText, { color: badge.text }]} numberOfLines={1}>
                                            #{prNumber}
                                        </Text>
                                    </View>
                                    <View style={styles.dot} />
                                </>
                            )}
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

const useStyles = createStyles(({ colors }) => ({
    unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.blue, marginRight: 6, flexShrink: 0 },
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
        fontWeight: '400',
    },
    unreadTitle: {
        fontWeight: '700',
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
    // The 14pt line plus the 1pt borders stays inside the 17pt meta line, so a badge does not make the row taller.
    prBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        flexShrink: 0,
        paddingHorizontal: 5,
        borderWidth: 1,
        borderRadius: radii.pill,
    },
    prText: {
        ...type.meta,
        lineHeight: 14,
        fontWeight: '500',
    },
    dot: {
        width: 3,
        height: 3,
        borderRadius: 1.5,
        backgroundColor: colors.dotSeparator,
    },
}))
