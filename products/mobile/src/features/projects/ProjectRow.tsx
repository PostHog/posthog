import type { ReactElement } from 'react'
import { ActivityIndicator, Text } from 'react-native'

import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface ProjectRowProps {
    label: string
    compact: boolean
    selected: boolean
    /** A switch to this row's account is in flight. */
    pending?: boolean
    disabled?: boolean
    onPress: () => void
    testID: string
}

export function ProjectRow({
    label,
    compact,
    selected,
    pending = false,
    disabled = false,
    onPress,
    testID,
}: ProjectRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled || pending}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected, busy: pending, disabled: disabled || pending }}
            accessibilityLabel={label}
            pressedBackground={colors.background}
            style={[styles.row, compact && styles.compact]}
            testID={testID}
        >
            <Text style={styles.label} numberOfLines={1}>
                {label}
            </Text>
            {pending ? (
                <ActivityIndicator color={colors.ink} accessibilityLabel="Switching" testID={`${testID}-switching`} />
            ) : selected ? (
                <CheckIcon size={iconSizes.control} />
            ) : null}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    compact: {
        minHeight: 44,
    },
    label: {
        ...type.label,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
}))
