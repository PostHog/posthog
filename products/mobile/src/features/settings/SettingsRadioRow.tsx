import type { ComponentType, ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface SettingsRadioRowProps {
    label: string
    selected: boolean
    onPress: () => void
    testID?: string
    /** Defaults to the label. */
    accessibilityLabel?: string
    Icon?: ComponentType<IconProps>
}

export function SettingsRadioRow({
    label,
    selected,
    onPress,
    testID,
    accessibilityLabel,
    Icon,
}: SettingsRadioRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={accessibilityLabel ?? label}
            pressedBackground={colors.background}
            style={styles.row}
            testID={testID}
        >
            {Icon ? <Icon size={iconSizes.control} color={colors.secondary} /> : null}
            <Text style={styles.label} numberOfLines={1}>
                {label}
            </Text>
            <View style={[styles.radio, selected && styles.radioSelected]}>
                {selected ? <View style={styles.radioDot} /> : null}
            </View>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
    },
    label: {
        ...type.body,
        color: colors.ink,
        flex: 1,
    },
    radio: {
        width: iconSizes.control,
        height: iconSizes.control,
        borderRadius: radii.pill,
        borderWidth: 1.5,
        borderColor: colors.control,
        alignItems: 'center',
        justifyContent: 'center',
    },
    radioSelected: {
        borderColor: colors.ink,
        backgroundColor: colors.ink,
    },
    radioDot: {
        width: 8,
        height: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.onInk,
    },
}))
