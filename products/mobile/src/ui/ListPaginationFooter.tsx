import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { Pressable44 } from './Pressable44'
import { createStyles, useColors } from './theme'
import { radii, type } from './tokens'

interface ListPaginationFooterProps {
    noun: string
    hasMore: boolean
    loading: boolean
    failed: boolean
    onLoadMore: () => void
}

export function ListPaginationFooter({
    noun,
    hasMore,
    loading,
    failed,
    onLoadMore,
}: ListPaginationFooterProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    if (loading) {
        return (
            <View style={styles.container} accessibilityLabel={`Loading more ${noun}`} accessibilityRole="progressbar">
                <ActivityIndicator color={colors.tertiary} />
            </View>
        )
    }
    if (!hasMore && !failed) {
        return null
    }
    return (
        <View style={styles.container}>
            {failed ? <Text style={styles.message}>Couldn't load more {noun}.</Text> : null}
            <Pressable44
                onPress={onLoadMore}
                accessibilityRole="button"
                accessibilityLabel={failed ? `Retry loading more ${noun}` : `Load more ${noun}`}
                style={styles.action}
                pressedBackground={colors.inkHover}
            >
                <Text style={styles.actionText}>{failed ? 'Try again' : 'Load more'}</Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    container: { alignItems: 'center', gap: 8, paddingVertical: 20 },
    message: { ...type.bodySmall, color: colors.muted, textAlign: 'center' },
    action: {
        height: 36,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actionText: { ...type.buttonSmall, color: colors.onInk },
}))
