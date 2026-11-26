import type { ReactElement, ReactNode } from 'react'
import { type StyleProp, Text, View, type ViewStyle } from 'react-native'

import { createStyles } from '@/ui/theme'
import { fonts, type } from '@/ui/tokens'

interface SettingsRowProps {
    label: string
    description?: string
    value?: string
    monoValue?: boolean
    accessory?: ReactNode
    style?: StyleProp<ViewStyle>
    testID?: string
}

export function SettingsRow({
    label,
    description,
    value,
    monoValue = false,
    accessory,
    style,
    testID,
}: SettingsRowProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.row, style]} testID={testID}>
            <View style={value ? undefined : styles.labelFill}>
                <Text style={styles.label}>{label}</Text>
                {description ? <Text style={styles.description}>{description}</Text> : null}
            </View>
            {value ? (
                <Text style={[styles.value, monoValue && styles.mono]} numberOfLines={1} ellipsizeMode="middle">
                    {value}
                </Text>
            ) : null}
            {accessory}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
        paddingVertical: 8,
    },
    label: {
        ...type.body,
        color: colors.ink,
        flexShrink: 0,
    },
    description: { ...type.metaSmall, color: colors.secondary, marginTop: 4 },
    labelFill: {
        flex: 1,
        flexShrink: 1,
    },
    value: {
        fontSize: 15,
        lineHeight: 21,
        color: colors.secondary,
        flex: 1,
        textAlign: 'right',
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 13,
    },
}))
