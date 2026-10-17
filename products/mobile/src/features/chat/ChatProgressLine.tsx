import type { ReactElement } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { colors, type } from '@/ui/tokens'

interface ChatProgressLineProps {
    text: string
}

export function ChatProgressLine({ text }: ChatProgressLineProps): ReactElement {
    return (
        <View style={styles.row} accessibilityRole="progressbar" accessibilityLabel={text} testID="chat-progress">
            <ActivityIndicator size="small" color={colors.tertiary} />
            <Text style={styles.text} numberOfLines={2}>
                {text}
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    text: {
        ...type.bodySmall,
        color: colors.tertiary,
        flexShrink: 1,
    },
})
