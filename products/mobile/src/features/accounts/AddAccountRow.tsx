import type { ReactElement } from 'react'
import { type StyleProp, Text, View, type ViewStyle } from 'react-native'

import { PlusIcon } from '@/ui/icons/PlusIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

interface AddAccountRowProps {
    onPress: () => void
    disabled?: boolean
    style?: StyleProp<ViewStyle>
    testID: string
}

export function AddAccountRow({ onPress, disabled = false, style, testID }: AddAccountRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityLabel="Add account"
            accessibilityState={{ disabled }}
            pressedBackground={colors.background}
            style={[styles.row, style]}
            testID={testID}
        >
            <View style={styles.plus}>
                <PlusIcon size={iconSizes.inline} color={colors.secondary} />
            </View>
            <Text style={[styles.label, disabled && styles.disabled]}>Add account</Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    plus: {
        width: 28,
        height: 28,
        borderRadius: 14,
        borderWidth: 1.5,
        borderStyle: 'dashed',
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    label: {
        ...type.body,
        color: colors.ink,
        flex: 1,
    },
    disabled: {
        color: colors.disabled,
    },
}))
