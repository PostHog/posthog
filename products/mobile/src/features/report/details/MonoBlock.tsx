import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { colors, radii, type } from '@/ui/tokens'

/** A fenced block, such as a stack trace or a query, on the same dark card as the report screen's trace. */
export function MonoBlock({ code }: { code: string }): ReactElement {
    return (
        <View style={styles.card}>
            <Text style={styles.code} selectable>
                {code}
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        backgroundColor: colors.ink,
        borderRadius: radii.card,
        paddingVertical: 14,
        paddingHorizontal: 16,
        marginBottom: 10,
        overflow: 'hidden',
    },
    code: {
        ...type.mono,
        color: colors.disabled,
    },
})
