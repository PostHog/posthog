import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { fonts, type } from '@/ui/tokens'

interface SettingsRowProps {
    label: string
    value?: string
    monoValue?: boolean
    accessory?: ReactNode
    testID?: string
}

export function SettingsRow({ label, value, monoValue = false, accessory, testID }: SettingsRowProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.row} testID={testID}>
            <Text style={[styles.label, value ? null : styles.labelFill]}>{label}</Text>
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
