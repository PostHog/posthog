import { type ReactElement, useState } from 'react'
import { type LayoutChangeEvent, Text, useWindowDimensions } from 'react-native'

import { PlusIcon } from '@/ui/icons/PlusIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface AddAccountButtonProps {
    onPress: () => void
    disabled?: boolean
    /**
     * The width the button can take. Null until the caller has measured it, which shows the label. When the label
     * does not fit, the button shows only the plus.
     */
    room: number | null
    testID: string
}

/** Add account in a card's title row, with the fill and height of the card's close button. */
export function AddAccountButton({ onPress, disabled = false, room, testID }: AddAccountButtonProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { fontScale } = useWindowDimensions()
    // A width measured at another text size is stale, so the button shows the label again to measure it.
    const [labeled, setLabeled] = useState<{ fontScale: number; width: number } | null>(null)
    const labeledWidth = labeled?.fontScale === fontScale ? labeled.width : null
    const showLabel = room === null || (labeledWidth === null ? room > 0 : labeledWidth <= room)
    const measureLabeled = (event: LayoutChangeEvent): void => {
        const { width } = event.nativeEvent.layout
        setLabeled((current) =>
            current?.fontScale === fontScale && current.width === width ? current : { fontScale, width }
        )
    }
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityLabel="Add account"
            accessibilityState={{ disabled }}
            pressedBackground={colors.hairline}
            onLayout={showLabel ? measureLabeled : undefined}
            style={showLabel ? styles.labeled : styles.iconOnly}
            testID={testID}
        >
            <PlusIcon size={iconSizes.control} color={disabled ? colors.disabled : colors.ink} />
            {showLabel ? (
                <Text style={[styles.label, disabled && styles.disabled]} numberOfLines={1}>
                    Add account
                </Text>
            ) : null}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    labeled: {
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingLeft: 12,
        paddingRight: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    iconOnly: {
        width: 44,
        height: 44,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    label: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
}))
