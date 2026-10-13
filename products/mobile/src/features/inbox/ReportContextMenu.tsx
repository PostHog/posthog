import { type ComponentType, type ReactElement, useState } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, useWindowDimensions, View } from 'react-native'
import { useSafeAreaFrame } from 'react-native-safe-area-context'

import type { InboxItem } from '@/model/types'
import { FloatingCard } from '@/ui/FloatingCard'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { ReassignIcon } from '@/ui/icons/ReassignIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { placeContextMenu, type RowAnchor } from './contextMenuPlacement'
import { INBOX_HEADER_BOTTOM } from './InboxHeader'

/** The bottom bar's design inset, the same one the inbox list pads its content by. */
const BOTTOM_BAR_ZONE = 120
const CARD_BORDER = 1

interface ReportContextMenuProps {
    visible: boolean
    item: InboxItem
    anchor: RowAnchor
    /** Dims Reassign while the report's current reviewers are unknown. */
    reassignDisabled: boolean
    onClose: () => void
    onReassign: () => void
    onSnooze: () => void
    onChat: () => void
    onMarkRead: () => void
}

interface ContextMenuRowProps {
    label: string
    Icon: ComponentType<IconProps>
    disabled?: boolean
    onPress: () => void
    testID: string
}

function ContextMenuRow({ label, Icon, disabled = false, onPress, testID }: ContextMenuRowProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityHint={disabled ? 'Loading the report' : undefined}
            pressedBackground={colors.sunken}
            style={styles.row}
            testID={testID}
        >
            <Icon size={22} color={disabled ? colors.disabled : colors.ink} />
            <Text style={[styles.rowLabel, disabled && styles.disabledLabel]}>{label}</Text>
        </Pressable44>
    )
}

export function ReportContextMenu({
    visible,
    item,
    anchor,
    reassignDisabled,
    onClose,
    onReassign,
    onSnooze,
    onChat,
    onMarkRead,
}: ReportContextMenuProps): ReactElement {
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
        topLimit: topOffset(insets, INBOX_HEADER_BOTTOM),
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
                <ContextMenuRow
                    label="Reassign"
                    Icon={ReassignIcon}
                    disabled={reassignDisabled}
                    onPress={onReassign}
                    testID="inbox-row-menu-reassign"
                />
                <ContextMenuRow label="Snooze" Icon={ClockIcon} onPress={onSnooze} testID="inbox-row-menu-snooze" />
                <ContextMenuRow label="Chat" Icon={ChatBubbleIcon} onPress={onChat} testID="inbox-row-menu-chat" />
                {item.read ? null : (
                    <ContextMenuRow
                        label="Mark as read"
                        Icon={CheckIcon}
                        onPress={onMarkRead}
                        testID="inbox-row-menu-mark-read"
                    />
                )}
            </View>
        </FloatingCard>
    )
}

const styles = StyleSheet.create({
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
        height: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 16,
        paddingHorizontal: 14,
        borderRadius: radii.menuRow,
    },
    rowLabel: {
        ...type.menuRow,
        color: colors.ink,
    },
    disabledLabel: {
        color: colors.disabled,
    },
})
