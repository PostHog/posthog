import { type ReactElement, useEffect, useState } from 'react'
import { Text, View } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { MenuCard, MenuDivider, MenuItem } from '@/features/views/list/ViewsMenu'
import type { ChatListItem } from '@/model/types'
import { ArchiveIcon } from '@/ui/icons/ArchiveIcon'
import { createStyles, useColors } from '@/ui/theme'
import { motion, type } from '@/ui/tokens'

export interface ChatRowMenuTarget {
    item: ChatListItem
    anchor: RowAnchor
}

interface ChatRowMenuProps {
    /** The row whose menu is open, or null when the menu is closed. */
    target: ChatRowMenuTarget | null
    onClose: () => void
    onArchive: (item: ChatListItem) => void
}

/** The long-press menu of a Chats row. It keeps the last row through the exit animation, then unmounts. */
export function ChatRowMenu({ target, onClose, onArchive }: ChatRowMenuProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const [shown, setShown] = useState(target)
    if (target !== null && target !== shown) {
        setShown(target)
    }
    useEffect(() => {
        if (target) {
            return undefined
        }
        const timer = setTimeout(() => setShown(null), motion.menu)
        return () => clearTimeout(timer)
    }, [target])

    if (!shown) {
        return null
    }
    const { item } = shown
    return (
        <MenuCard
            visible={target !== null}
            anchor={shown.anchor}
            onClose={onClose}
            accessibilityLabel={`${item.title} actions`}
            testID="chat-row-menu"
        >
            <View style={styles.header}>
                <Text style={styles.title} numberOfLines={2}>
                    {item.title}
                </Text>
            </View>
            <MenuDivider />
            <MenuItem
                label="Archive"
                onPress={() => onArchive(item)}
                trailing={<ArchiveIcon size={18} color={colors.ink} />}
                testID="chat-row-menu-archive"
            />
        </MenuCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    header: {
        paddingHorizontal: 10,
        paddingTop: 8,
        paddingBottom: 10,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
}))
