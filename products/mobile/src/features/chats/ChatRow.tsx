import { memo, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useMenuTrigger } from '@/features/views/list/useMenuTrigger'
import { formatRelativeAgo } from '@/lib/dates'
import type { ChatListItem, ChatOrigin } from '@/model/types'
import { Dot } from '@/ui/Dot'
import { IconTile } from '@/ui/IconTile'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { sessionStatusDisplay } from './sessionStatus'

interface ChatRowProps {
    item: ChatListItem
    now: Date
    onOpen: (item: ChatListItem) => void
    onLongPress: (item: ChatListItem, anchor: RowAnchor) => void
}

const ORIGIN_LABEL: Record<ChatOrigin, string> = {
    chat: 'Chat',
    report: 'Report',
    session: 'Session',
}

export const ChatRow = memo(function ChatRow({ item, now, onOpen, onLongPress }: ChatRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(item, onLongPress)
    const when = formatRelativeAgo(item.updatedAt, now)
    const status = sessionStatusDisplay(item.status, colors)
    const origin = ORIGIN_LABEL[item.origin]
    const metaText = `${origin}, ${status.label}, ${when}`
    return (
        <Pressable44
            ref={menu.ref}
            onPress={() => onOpen(item)}
            onLongPress={menu.onLongPress}
            accessibilityActions={menu.accessibilityActions}
            onAccessibilityAction={menu.onAccessibilityAction}
            pressedBackground={colors.sunken}
            style={styles.row}
            accessibilityLabel={`${item.title}, ${metaText}${item.pullRequestUrl ? ', has a pull request' : ''}`}
            testID={`chat-row-${item.id.replace(':', '-')}`}
        >
            <IconTile>
                {item.origin === 'chat' ? (
                    <ChatBubbleIcon size={iconSizes.navigation} />
                ) : (
                    <GitBranchIcon size={iconSizes.navigation} />
                )}
            </IconTile>
            <View style={styles.body}>
                <Text style={styles.title} numberOfLines={1}>
                    {item.title}
                </Text>
                <View style={styles.meta}>
                    <Text style={styles.metaText} numberOfLines={1}>
                        {origin}
                    </Text>
                    <View style={styles.separator} />
                    <Dot color={status.dotColor} />
                    <Text style={styles.metaText} numberOfLines={1}>
                        {status.label}
                    </Text>
                    <View style={styles.separator} />
                    <Text style={styles.metaText} numberOfLines={1}>
                        {when}
                    </Text>
                    {item.pullRequestUrl ? (
                        <View style={styles.chip}>
                            <MonoText size={11} color={colors.secondary}>
                                PR
                            </MonoText>
                        </View>
                    ) : null}
                </View>
            </View>
        </Pressable44>
    )
})

const useStyles = createStyles(({ colors }) => ({
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
    separator: {
        width: 3,
        height: 3,
        borderRadius: 1.5,
        backgroundColor: colors.dotSeparator,
    },
    chip: {
        paddingHorizontal: 6,
        borderRadius: radii.markSmall,
        backgroundColor: colors.sunken,
    },
}))
