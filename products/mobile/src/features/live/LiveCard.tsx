import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface LiveCardProps {
    title?: string
    meta?: string
    children: ReactNode
    /** Rows that run to the card's edges, such as the events feed. */
    flush?: boolean
    /** Makes the whole card one button, such as the map card that opens Visitors by country. */
    onPress?: () => void
    accessibilityLabel?: string
    testID?: string
}

export function LiveCard({
    title,
    meta,
    children,
    flush = false,
    onPress,
    accessibilityLabel,
    testID,
}: LiveCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const content = (
        <>
            {title ? (
                <View style={[styles.head, flush && styles.flushHead]}>
                    <Text style={styles.title} accessibilityRole="header" numberOfLines={2}>
                        {title}
                    </Text>
                    {meta ? <Text style={styles.meta}>{meta}</Text> : null}
                </View>
            ) : null}
            {children}
        </>
    )
    const style = [styles.card, flush && styles.flush]
    if (onPress) {
        return (
            <Pressable44
                onPress={onPress}
                accessibilityLabel={accessibilityLabel}
                pressedBackground={colors.pressed}
                hitSlop={0}
                style={style}
                testID={testID}
            >
                {content}
            </Pressable44>
        )
    }
    return (
        <View style={style} testID={testID}>
            {content}
        </View>
    )
}

export function LiveCardNote({ text, testID }: { text: string; testID?: string }): ReactElement {
    const styles = useStyles()
    return (
        <Text style={styles.note} testID={testID}>
            {text}
        </Text>
    )
}

export const NOT_LOADED_TEXT = "Couldn't load this yet. Live tries again every 30 seconds."

const useStyles = createStyles(({ colors }) => ({
    card: {
        gap: 12,
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    flush: {
        paddingHorizontal: 0,
        paddingBottom: 0,
        gap: 4,
    },
    head: {
        flexDirection: 'row',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        gap: 12,
    },
    flushHead: {
        paddingHorizontal: 14,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
        flexShrink: 1,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
    note: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
        paddingVertical: 24,
    },
}))
