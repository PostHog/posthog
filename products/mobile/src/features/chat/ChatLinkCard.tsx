import type { ReactElement } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

interface ChatLinkCardProps {
    text: string
    url?: string
}

export function ChatLinkCard({ text, url }: ChatLinkCardProps): ReactElement {
    return (
        <View style={styles.card} testID="chat-link">
            <Text style={styles.text}>{text}</Text>
            {url ? (
                <Pressable44
                    onPress={() => {
                        Linking.openURL(url).catch(() => undefined)
                    }}
                    accessibilityRole="link"
                    pressedBackground={colors.background}
                    style={styles.open}
                >
                    <Text style={styles.openText}>Open in PostHog</Text>
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
        backgroundColor: colors.background,
        paddingVertical: 12,
        paddingHorizontal: 14,
        gap: 10,
    },
    text: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    open: {
        alignSelf: 'flex-start',
        height: 36,
        paddingHorizontal: 14,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        backgroundColor: colors.white,
        justifyContent: 'center',
    },
    openText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
