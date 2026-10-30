import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface InboxListFooterProps {
    isLoadingMore: boolean
    loadMoreFailed: boolean
    onRetry: () => void
}

export function InboxListFooter({ isLoadingMore, loadMoreFailed, onRetry }: InboxListFooterProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    if (isLoadingMore) {
        return (
            <View style={styles.container} accessibilityLabel="Loading more reports" accessibilityRole="progressbar">
                <ActivityIndicator color={colors.tertiary} />
            </View>
        )
    }
    if (loadMoreFailed) {
        return (
            <View style={styles.container} testID="inbox-load-more-error">
                <Text style={styles.message}>Couldn't load more reports.</Text>
                <Pressable44 onPress={onRetry} style={styles.action} pressedBackground={colors.inkHover}>
                    <Text style={styles.actionText}>Try again</Text>
                </Pressable44>
            </View>
        )
    }
    return null
}

const useStyles = createStyles(({ colors }) => ({
    container: {
        alignItems: 'center',
        gap: 8,
        paddingVertical: 20,
    },
    message: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
    },
    action: {
        height: 36,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actionText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
