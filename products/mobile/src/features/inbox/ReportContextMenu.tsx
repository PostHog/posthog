import { type ComponentType, type ReactElement, type ReactNode, useState } from 'react'
import { ActivityIndicator, type LayoutChangeEvent, Text, useWindowDimensions, View } from 'react-native'
import { useSafeAreaFrame } from 'react-native-safe-area-context'

import type { InboxItem } from '@/model/types'
import { FloatingCard } from '@/ui/FloatingCard'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { EyeOffIcon } from '@/ui/icons/EyeOffIcon'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { MailOpenIcon } from '@/ui/icons/MailOpenIcon'
import { MailUnreadIcon } from '@/ui/icons/MailUnreadIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { ReassignIcon } from '@/ui/icons/ReassignIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { TABS_HEADER_BOTTOM } from '../tabs/TabsHeader'
import { placeContextMenu, type RowAnchor } from './contextMenuPlacement'

/** The bottom bar's design inset, the same one the inbox list pads its content by. */
const BOTTOM_BAR_ZONE = 120
const CARD_BORDER = 1

interface ReportContextMenuProps {
    visible: boolean
    item: InboxItem
    anchor: RowAnchor
    /** Dims Reassign while the report's current reviewers are unknown. */
    reassignDisabled: boolean
    handoffLabel: string
    showHandoff: boolean
    handoffDisabled: boolean
    handoffPending: boolean
    handoffError?: string
    onHandOff: () => void
    /** Replaces the handoff row: a report with a PR is past handing off. */
    showPullRequest: boolean
    /** Dims View PR when the PR link is not an https URL the phone can open. */
    pullRequestDisabled: boolean
    onViewPullRequest: () => void
    onClose: () => void
    onReassign: () => void
    onResolve: () => void
    onDismiss: () => void
    onChat: () => void
    onMarkRead: () => void
    onMarkUnread: () => void
}

interface ContextMenuRowProps {
    label: string
    Icon: ComponentType<IconProps>
    disabled?: boolean
    pending?: boolean
    trailing?: ReactNode
    onPress: () => void
    testID: string
}

function ContextMenuRow({
    label,
    Icon,
    disabled = false,
    pending = false,
    trailing,
    onPress,
    testID,
}: ContextMenuRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityState={{ busy: pending, disabled }}
            pressedBackground={colors.sunken}
            style={styles.row}
            testID={testID}
        >
            <View style={styles.icon}>
                {pending ? (
                    <ActivityIndicator size="small" color={colors.ink} />
                ) : (
                    <Icon size={iconSizes.control} color={disabled ? colors.disabled : colors.ink} />
                )}
            </View>
            <Text style={[styles.rowLabel, disabled && styles.disabledLabel]}>{label}</Text>
            {trailing}
        </Pressable44>
    )
}

export function ReportContextMenu({
    visible,
    item,
    anchor,
    reassignDisabled,
    handoffLabel,
    showHandoff,
    handoffDisabled,
    handoffPending,
    handoffError,
    onHandOff,
    showPullRequest,
    pullRequestDisabled,
    onViewPullRequest,
    onClose,
    onReassign,
    onResolve,
    onDismiss,
    onChat,
    onMarkRead,
    onMarkUnread,
}: ReportContextMenuProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const insets = useScreenInsets()
    const { width: windowWidth } = useWindowDimensions()
    // The overlay covers the full screen, which on Android edge-to-edge includes the navigation bar that the window height leaves out.
    const { height: screenHeight } = useSafeAreaFrame()
    const [height, setHeight] = useState<number | null>(null)
    const [wasVisible, setWasVisible] = useState(visible)
    const [opens, setOpens] = useState(0)
    // A reopened menu can have different rows, so it is measured again before the first frame shows it. The content
    // remounts on each open, so `onLayout` fires even when the card is still mounted from the last exit animation.
    if (visible !== wasVisible) {
        setWasVisible(visible)
        if (visible) {
            setHeight(null)
            setOpens(opens + 1)
        }
    }
    // The handoff's 75% width is the content box; padding and border add 22pt.
    const width = Math.round(windowWidth * 0.75) + 22
    const placement = placeContextMenu({
        rowTop: anchor.y,
        rowBottom: anchor.y + anchor.height,
        menuHeight: height ?? 0,
        topLimit: topOffset(insets, TABS_HEADER_BOTTOM),
        bottomLimit: screenHeight - bottomOffset(insets, BOTTOM_BAR_ZONE),
    })
    // Until the first layout the card sits off screen, so it never shows at a spot picked without its height.
    const top = height === null ? -screenHeight : placement.top
    const onLayout = (event: LayoutChangeEvent): void => {
        setHeight(event.nativeEvent.layout.height + CARD_BORDER * 2)
    }
    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            transformOrigin={placement.side === 'below' ? 'top left' : 'bottom left'}
            accessibilityLabel="Report actions"
            testID="inbox-row-menu"
            style={[styles.card, { top, width }]}
        >
            <View key={opens} style={styles.content} onLayout={onLayout}>
                <View style={styles.header}>
                    <Text style={styles.title} numberOfLines={2}>
                        {item.title}
                    </Text>
                    <Text style={styles.source} numberOfLines={1}>
                        {item.sourceLabel}
                    </Text>
                </View>
                <View style={styles.divider} />
                {showPullRequest ? (
                    <ContextMenuRow
                        label="View PR"
                        Icon={GitBranchIcon}
                        disabled={pullRequestDisabled}
                        trailing={
                            <ExternalLinkIcon
                                size={16}
                                color={pullRequestDisabled ? colors.disabled : colors.tertiary}
                            />
                        }
                        onPress={onViewPullRequest}
                        testID="inbox-row-menu-view-pr"
                    />
                ) : null}
                {showHandoff ? (
                    <ContextMenuRow
                        label={handoffLabel}
                        Icon={PlayIcon}
                        disabled={handoffDisabled || handoffPending}
                        pending={handoffPending}
                        onPress={onHandOff}
                        testID="inbox-row-menu-handoff"
                    />
                ) : null}
                {handoffError ? (
                    <Text style={styles.error} accessibilityRole="alert" testID="inbox-row-menu-handoff-error">
                        {handoffError}
                    </Text>
                ) : null}
                <ContextMenuRow
                    label="Reassign"
                    Icon={ReassignIcon}
                    disabled={reassignDisabled || handoffPending}
                    onPress={onReassign}
                    testID="inbox-row-menu-reassign"
                />
                <ContextMenuRow
                    label="Resolve"
                    disabled={handoffPending}
                    Icon={CheckCircleIcon}
                    onPress={onResolve}
                    testID="inbox-row-menu-resolve"
                />
                <ContextMenuRow
                    label="Dismiss"
                    disabled={handoffPending}
                    Icon={EyeOffIcon}
                    onPress={onDismiss}
                    testID="inbox-row-menu-dismiss"
                />
                <ContextMenuRow
                    label="Chat"
                    disabled={handoffPending}
                    Icon={ChatBubbleIcon}
                    onPress={onChat}
                    testID="inbox-row-menu-chat"
                />
                {item.read ? (
                    <ContextMenuRow
                        label="Mark as unread"
                        disabled={handoffPending}
                        Icon={MailUnreadIcon}
                        onPress={onMarkUnread}
                        testID="inbox-row-menu-mark-unread"
                    />
                ) : (
                    <ContextMenuRow
                        label="Mark as read"
                        disabled={handoffPending}
                        Icon={MailOpenIcon}
                        onPress={onMarkRead}
                        testID="inbox-row-menu-mark-read"
                    />
                )}
            </View>
        </FloatingCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        left: layout.inboxGutter,
        borderWidth: CARD_BORDER,
        borderColor: colors.hairline,
    },
    content: {
        paddingTop: 8,
        paddingHorizontal: 10,
        paddingBottom: 12,
    },
    header: {
        paddingHorizontal: 14,
        paddingTop: 10,
        paddingBottom: 12,
        gap: 3,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
    source: {
        ...type.meta,
        color: colors.secondary,
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
        marginHorizontal: 4,
        marginBottom: 6,
    },
    row: {
        minHeight: 52,
        paddingVertical: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 16,
        paddingHorizontal: 14,
        borderRadius: radii.menuRow,
    },
    icon: { width: iconSizes.control, alignItems: 'center' },
    error: { ...type.metaSmall, color: colors.orange, paddingHorizontal: 14, paddingVertical: 8 },
    rowLabel: {
        ...type.menuRow,
        color: colors.ink,
        flex: 1,
    },
    disabledLabel: {
        color: colors.disabled,
    },
}))
