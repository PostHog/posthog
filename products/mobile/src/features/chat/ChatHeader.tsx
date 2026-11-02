import { type ReactElement, type RefObject, useState } from 'react'
import { View } from 'react-native'

import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { ChatHeaderMenu } from './ChatHeaderMenu'
import { useCopyChatLink } from './useCopyChatLink'

const HEADER_TOP = 16
const ROW_HEIGHT = 54
const HEADER_FADE = 24
export const CHAT_HEADER_HEIGHT = HEADER_TOP + ROW_HEIGHT + HEADER_FADE

interface ChatHeaderProps {
    webUrl: string | undefined
    blurTarget?: RefObject<View | null>
    onBack: () => void
    onNewChat: () => void
    onArchive?: () => Promise<void>
}

export function ChatHeader({ webUrl, blurTarget, onBack, onNewChat, onArchive }: ChatHeaderProps): ReactElement {
    const colors = useColors()
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
        <View collapsable={false} style={[styles.header, { paddingTop: insets.top + HEADER_TOP }]} testID="chat-header">
            <BlurEdge solid={0.7} blurTarget={blurTarget} />
            <FadeEdge direction="down" solid={0.7} opacity={layout.chromeTint} />
            <Pressable44
                onPress={onBack}
                accessibilityLabel="Back"
                pressedBackground={colors.background}
                style={styles.round}
                testID="chat-back"
            >
                <ChevronLeftIcon size={iconSizes.control} />
            </Pressable44>
            <PillControl height={ROW_HEIGHT}>
                <Pressable44
                    onPress={onNewChat}
                    accessibilityLabel="New chat"
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="chat-new"
                >
                    <ComposeIcon size={iconSizes.control} />
                </Pressable44>
                <Pressable44
                    onPress={() => setMenuOpen(true)}
                    accessibilityLabel="Chat options"
                    accessibilityState={{ expanded: menuOpen, disabled: !webUrl && !onArchive }}
                    disabled={!webUrl && !onArchive}
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="chat-more"
                >
                    <MoreIcon size={iconSizes.control} color={webUrl || onArchive ? colors.ink : colors.disabled} />
                </Pressable44>
            </PillControl>
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

const useStyles = createStyles(({ colors }) => ({
    header: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: 16,
        paddingBottom: HEADER_FADE,
        pointerEvents: 'box-none',
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    round: {
        width: 44,
        height: 44,
        borderRadius: 22,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
