import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { PinIcon } from '@/ui/icons/PinIcon'
import { colors, radii, type } from '@/ui/tokens'

/** Pinned with nothing in it: what pinning does and how to do it, with Recent right below. */
export function EmptyPins(): ReactElement {
    return (
        <View style={styles.card} testID="views-pins-empty">
            <View style={styles.icon}>
                <PinIcon size={20} color={colors.blue} />
            </View>
            <Text style={styles.title}>Nothing pinned yet</Text>
            <Text style={styles.body}>
                Tap the pin on any dashboard or insight to pin them to the top of the Views page.
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        gap: 6,
        alignItems: 'flex-start',
        paddingVertical: 18,
        paddingHorizontal: 16,
        borderWidth: 1,
        borderStyle: 'dashed',
        borderColor: colors.border,
        borderRadius: radii.option,
        backgroundColor: colors.white,
    },
    icon: {
        width: 36,
        height: 36,
        borderRadius: radii.tile,
        backgroundColor: colors.blueHighlight,
        alignItems: 'center',
        justifyContent: 'center',
    },
    title: {
        fontSize: 17,
        fontWeight: '700',
        lineHeight: 24,
        marginTop: 4,
        color: colors.ink,
    },
    body: {
        ...type.bodySmall,
        color: colors.muted,
    },
})
