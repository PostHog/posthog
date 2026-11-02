import type { ReactElement } from 'react'
import { ActivityIndicator, useWindowDimensions } from 'react-native'

import { MenuDivider, MenuItem } from '@/features/views/list/ViewsMenu'
import { FloatingCard } from '@/ui/FloatingCard'
import { ArchiveIcon } from '@/ui/icons/ArchiveIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { createStyles, useColors } from '@/ui/theme'

interface ChatHeaderMenuProps {
    visible: boolean
    top: number
    copying: boolean
    archiving: boolean
    canCopy: boolean
    canArchive: boolean
    onCopy: () => void
    onArchive: () => void
    onClose: () => void
}

export function ChatHeaderMenu({
    visible,
    top,
    copying,
    archiving,
    canCopy,
    canArchive,
    onCopy,
    onArchive,
    onClose,
}: ChatHeaderMenuProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { width } = useWindowDimensions()
    const busy = copying || archiving
    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            transformOrigin="top right"
            accessibilityLabel="Chat options"
            testID="chat-header-menu"
            style={[styles.menu, { top, width: Math.min(272, width - 32) }]}
        >
            <MenuItem
                label="Copy link to chat"
                onPress={onCopy}
                disabled={!canCopy || busy}
                trailing={copying ? <ActivityIndicator size="small" color={colors.ink} /> : <CopyIcon size={18} />}
                testID="chat-copy-link"
            />
            <MenuDivider />
            <MenuItem
                label="Archive chat"
                onPress={onArchive}
                disabled={!canArchive || busy}
                trailing={archiving ? <ActivityIndicator size="small" color={colors.ink} /> : <ArchiveIcon size={18} />}
                testID="chat-archive"
            />
        </FloatingCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    menu: {
        right: 16,
        padding: 6,
        borderRadius: 16,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
}))
