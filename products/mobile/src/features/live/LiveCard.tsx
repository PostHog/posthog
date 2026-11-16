import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface LiveCardProps {
    title?: string
    meta?: string
    children: ReactNode
    /** Rows that run to the card's edges, such as the events feed. */
    flush?: boolean
    testID?: string
}

export function LiveCard({ title, meta, children, flush = false, testID }: LiveCardProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.card, flush && styles.flush]} testID={testID}>
            {title ? (
                <View style={[styles.head, flush && styles.flushHead]}>
                    <Text style={styles.title} accessibilityRole="header" numberOfLines={2}>
                        {title}
                    </Text>
                    {meta ? <Text style={styles.meta}>{meta}</Text> : null}
                </View>
            ) : null}
            {children}
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
