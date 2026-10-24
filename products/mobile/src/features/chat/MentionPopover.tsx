import type { ReactElement } from 'react'
import { ScrollView, Text, View } from 'react-native'

import { formatRelativeAgo } from '@/lib/dates'
import type { InboxItem } from '@/model/types'
import { Dot } from '@/ui/Dot'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface MentionPopoverProps {
    items: InboxItem[]
    now: Date
    onPick: (item: InboxItem) => void
}

export function MentionPopover({ items, now, onPick }: MentionPopoverProps): ReactElement {
    const { colors, shadows, accentColor } = useTheme()
    const styles = useStyles()
    return (
        <View style={[styles.popover, shadows.popover]} testID="mention-popover">
            <ScrollView keyboardShouldPersistTaps="handled">
                <Text style={[type.eyebrow, styles.eyebrow]}>ADD A REPORT</Text>
                {items.map((item) => (
                    <Pressable44
                        key={item.id}
                        onPress={() => onPick(item)}
                        pressedBackground={colors.background}
                        style={styles.row}
                        testID={`mention-${item.reportId}`}
                    >
                        <Dot color={accentColor[item.accent]} size={9} />
                        <Text style={styles.title} numberOfLines={1}>
                            {item.title}
                        </Text>
                        <Text style={styles.date}>{formatRelativeAgo(item.updatedAt, now)}</Text>
                    </Pressable44>
                ))}
            </ScrollView>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    popover: {
        position: 'absolute',
        left: 10,
        right: 10,
        bottom: '100%',
        marginBottom: 8,
        zIndex: 5,
        // 260pt content box plus 6pt padding and a 1pt border on each side.
        maxHeight: 274,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.menuRow,
        backgroundColor: colors.surface,
        padding: 6,
    },
    eyebrow: {
        color: colors.tertiary,
        paddingTop: 8,
        paddingHorizontal: 12,
        paddingBottom: 6,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        // 44pt content box plus 6pt padding on each side.
        minHeight: 56,
        paddingVertical: 6,
        paddingHorizontal: 12,
        borderRadius: radii.card,
    },
    title: {
        flex: 1,
        minWidth: 0,
        fontSize: 15,
        lineHeight: 21,
        fontWeight: '500',
        color: colors.ink,
    },
    date: {
        fontSize: 12,
        lineHeight: 16.8,
        color: colors.tertiary,
    },
}))
