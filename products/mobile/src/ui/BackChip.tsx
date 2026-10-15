import type { ReactElement } from 'react'
import { StyleSheet, Text } from 'react-native'

import { ChevronLeftIcon } from './icons/ChevronLeftIcon'
import { Pressable44 } from './Pressable44'
import { colors, iconSizes, radii, shadows, type } from './tokens'

interface BackChipProps {
    onPress: () => void
    testID?: string
}

export function BackChip({ onPress, testID }: BackChipProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel="Back"
            style={[styles.chip, shadows.chip]}
            pressedStyle={styles.pressed}
            testID={testID}
        >
            <ChevronLeftIcon size={iconSizes.control} />
            <Text style={styles.text}>Back</Text>
        </Pressable44>
    )
}

const styles = StyleSheet.create({
    // 44pt content box plus a 1pt border on each side.
    chip: {
        height: 46,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingLeft: 12,
        paddingRight: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
    },
    pressed: {
        borderColor: colors.disabled,
    },
    text: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
