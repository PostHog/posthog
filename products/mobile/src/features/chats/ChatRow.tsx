import { memo, type ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { formatRelativeAgo } from '@/lib/dates'
import type { ChatListItem } from '@/model/types'
import { Dot } from '@/ui/Dot'
import { IconTile } from '@/ui/IconTile'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

import { sessionStatusDisplay } from './sessionStatus'

interface ChatRowProps {
    item: ChatListItem
    now: Date
    onOpen: (item: ChatListItem) => void
}

export const ChatRow = memo(function ChatRow({ item, now, onOpen }: ChatRowProps): ReactElement {
    const when = formatRelativeAgo(item.updatedAt, now)
    const status = item.kind === 'session' && item.status ? sessionStatusDisplay(item.status) : null
    const metaText = status ? `${status.label}, ${when}` : when
    // A session opens in the web app, so without a web URL (demo mode) it has nowhere to go.
    const disabled = item.kind === 'session' && !item.webUrl
    return (
        <Pressable44
            onPress={() => onOpen(item)}
            disabled={disabled}
            pressedBackground={colors.sunken}
            style={[styles.row, disabled && styles.disabled]}
            accessibilityLabel={`${item.title}, ${metaText}${item.pullRequestUrl ? ', has a pull request' : ''}`}
            accessibilityState={{ disabled }}
            testID={`chat-row-${item.id.replace(':', '-')}`}
        >
            <IconTile>{item.kind === 'session' ? <GitBranchIcon size={18} /> : <ChatBubbleIcon size={18} />}</IconTile>
            <View style={styles.body}>
                <Text style={styles.title} numberOfLines={1}>
                    {item.title}
                </Text>
                <View style={styles.meta}>
                    {status ? (
                        <>
                            <Dot color={status.dotColor} />
                            <Text style={styles.metaText} numberOfLines={1}>
                                {status.label}
                            </Text>
                            <View style={styles.separator} />
                        </>
                    ) : null}
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
    disabled: {
        opacity: 0.4,
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
})
