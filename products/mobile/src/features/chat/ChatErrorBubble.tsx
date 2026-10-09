import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

interface ChatErrorBubbleProps {
    text: string
    onRetry?: () => void
}

export function ChatErrorBubble({ text, onRetry }: ChatErrorBubbleProps): ReactElement {
    return (
        <View style={styles.card} testID="chat-error">
            <View style={styles.row}>
                <WarningIcon size={18} color={colors.orange} />
                <Text style={styles.text}>{text}</Text>
            </View>
            {onRetry ? (
                <Pressable44
                    onPress={onRetry}
                    pressedBackground={colors.background}
                    style={styles.retry}
                    testID="chat-retry"
                >
                    <Text style={styles.retryText}>Try again</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        alignSelf: 'stretch',
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.menuRow,
        paddingVertical: 12,
        paddingHorizontal: 14,
        gap: 10,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
    },
    text: {
        ...type.bodySmall,
        color: colors.ink,
        flex: 1,
    },
    retry: {
        alignSelf: 'flex-start',
        height: 36,
        paddingHorizontal: 14,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        justifyContent: 'center',
        marginLeft: 28,
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
