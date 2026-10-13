import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

interface ChatsPartialNoticeProps {
    onRetry: () => void
}

export function ChatsPartialNotice({ onRetry }: ChatsPartialNoticeProps): ReactElement {
    return (
        <View style={styles.row} accessibilityRole="alert" testID="chats-partial-error">
            <WarningIcon size={16} color={colors.orange} />
            <Text style={styles.text} numberOfLines={1}>
                Some chats didn't load.
            </Text>
            <Pressable44
                onPress={onRetry}
                accessibilityLabel="Try again"
                pressedBackground={colors.sunken}
                style={styles.retry}
                testID="chats-partial-retry"
            >
                <Text style={styles.retryText}>Try again</Text>
            </Pressable44>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 4,
        marginTop: 4,
    },
    text: {
        ...type.metaSmall,
        color: colors.orange,
        flexShrink: 1,
    },
    retry: {
        height: 32,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
