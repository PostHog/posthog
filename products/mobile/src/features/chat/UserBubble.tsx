import { memo, type ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { colors, radii, type } from '@/ui/tokens'

interface UserBubbleProps {
    text: string
}

export const UserBubble = memo(function UserBubble({ text }: UserBubbleProps): ReactElement {
    return (
        <View style={styles.bubble}>
            <Text style={styles.text}>{text}</Text>
        </View>
    )
})

const styles = StyleSheet.create({
    bubble: {
        alignSelf: 'flex-end',
        maxWidth: '82%',
        backgroundColor: colors.sunken,
        borderRadius: radii.menuRow,
        paddingVertical: 10,
        paddingHorizontal: 14,
    },
    text: {
        ...type.body,
        color: colors.ink,
    },
})
