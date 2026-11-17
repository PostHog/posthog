import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii } from '@/ui/tokens'

interface AccountActionButtonProps {
    label: string
    onPress: () => void
    disabled?: boolean
    /** Defaults to the label. */
    accessibilityLabel?: string
    testID: string
}

/** The small bordered button beside an account: Sign in again, Sign out, Try again. */
export function AccountActionButton({
    label,
    onPress,
    disabled = false,
    accessibilityLabel,
    testID,
}: AccountActionButtonProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityLabel={accessibilityLabel ?? label}
            accessibilityState={{ disabled }}
            pressedBackground={colors.sunken}
            style={styles.button}
            testID={testID}
        >
            <Text style={[styles.text, disabled && styles.disabled]}>{label}</Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    // 32pt visual; Pressable44's hit slop brings the target to 44pt.
    button: {
        height: 32,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
    },
    text: {
        fontSize: 14,
        lineHeight: 20,
        fontWeight: '600',
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
}))
