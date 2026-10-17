import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { WarningIcon } from '@/ui/icons/WarningIcon'
import { colors, iconSizes, radii, type } from '@/ui/tokens'

interface ChatErrorBubbleProps {
    text: string
}

export function ChatErrorBubble({ text }: ChatErrorBubbleProps): ReactElement {
    return (
        <View style={styles.card} testID="chat-error">
            <View style={styles.row}>
                <WarningIcon size={iconSizes.control} color={colors.orange} />
                <Text style={styles.text}>{text}</Text>
            </View>
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
})
