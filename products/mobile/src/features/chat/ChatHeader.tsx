import { type ReactElement, type RefObject, useState } from 'react'
import type { ViewInstance } from 'react-native'
import { View } from 'react-native'

import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { BackChip } from '@/ui/BackChip'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { screenLayout } from '@/ui/screenLayout'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, layout, radii } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { ChatHeaderMenu } from './ChatHeaderMenu'
import { useCopyChatLink } from './useCopyChatLink'

const HEADER_TOP = screenLayout.top - layout.designStatusBar
const ROW_HEIGHT = screenLayout.rowHeight
const HEADER_FADE = 24
export const CHAT_HEADER_HEIGHT = HEADER_TOP + ROW_HEIGHT + HEADER_FADE
export const CHAT_COMPACT_HEADER_HEIGHT = HEADER_TOP + ROW_HEIGHT + 8

interface ChatHeaderProps {
    compact?: boolean
    webUrl: string | undefined
    blurTarget?: RefObject<ViewInstance | null>
    onBack: () => void
    onNewChat: () => void
    newChatDisabledReason?: string
    onArchive?: () => Promise<void>
}

export function ChatHeader({
    compact = false,
    webUrl,
    blurTarget,
    onBack,
    onNewChat,
    newChatDisabledReason,
    onArchive,
}: ChatHeaderProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const [menuOpen, setMenuOpen] = useState(false)
    const toasts = useToasts()
    const { copyLink, copying } = useCopyChatLink(toasts.show)
    const archive = useAsyncAction(async () => {
        if (!onArchive) {
            return
        }
        try {
            await onArchive()
            setMenuOpen(false)
        } catch {
            toasts.show("Couldn't archive this chat. Try again.")
        }
    })
    const copy = async (): Promise<void> => {
        if (await copyLink(webUrl)) {
            setMenuOpen(false)
        }
    }
    return (
        <View
            collapsable={false}
            style={[
                styles.header,
                {
                    paddingTop: insets.top + HEADER_TOP,
                    paddingBottom: compact ? 8 : HEADER_FADE,
                    height: insets.top + (compact ? CHAT_COMPACT_HEADER_HEIGHT : CHAT_HEADER_HEIGHT),
                },
            ]}
            testID="chat-header"
        >
            <BlurEdge solid={0.7} blurTarget={blurTarget} />
            <FadeEdge direction="down" solid={0.7} opacity={layout.chromeTint} />
            <BackChip onPress={onBack} testID="chat-back" />
            {webUrl || onArchive ? (
                <PillControl height={ROW_HEIGHT} style={[styles.actions, shadows.chip]}>
                    <Pressable44
                        onPress={() => (newChatDisabledReason ? toasts.show(newChatDisabledReason) : onNewChat())}
                        accessibilityLabel="New chat"
                        accessibilityState={{ disabled: !!newChatDisabledReason }}
                        accessibilityHint={newChatDisabledReason}
                        pressedBackground={colors.background}
                        style={styles.button}
                        testID="chat-new"
                    >
                        <ComposeIcon size={iconSizes.control} />
                    </Pressable44>
                    <Pressable44
                        onPress={() => setMenuOpen(true)}
                        accessibilityLabel="Chat options"
                        accessibilityState={{ expanded: menuOpen }}
                        pressedBackground={colors.background}
                        style={styles.button}
                        testID="chat-more"
                    >
                        <MoreIcon size={iconSizes.control} />
                    </Pressable44>
                </PillControl>
            ) : null}
            <ChatHeaderMenu
                visible={menuOpen}
                top={insets.top + HEADER_TOP + ROW_HEIGHT + 8}
                copying={copying}
                archiving={archive.pending}
                canCopy={!!webUrl}
                canArchive={!!onArchive}
                onCopy={() => void copy()}
                onArchive={() => void archive.run()}
                onClose={() => setMenuOpen(false)}
            />
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={28} />
        </View>
    )
}

const useStyles = createStyles(() => ({
    header: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.detailGutter,
        paddingBottom: HEADER_FADE,
        pointerEvents: 'box-none',
    },
    button: {
        width: 48,
        height: 44,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actions: {
        paddingVertical: 0,
        paddingHorizontal: 0,
    },
}))
