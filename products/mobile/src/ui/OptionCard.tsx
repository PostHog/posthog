import { type ComponentType, Fragment, type ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { CheckIcon } from '@/ui/icons/CheckIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, space, type } from '@/ui/tokens'

export interface OptionCardItem<K extends string> {
    key: K
    label: string
    description?: string
    Icon: ComponentType<IconProps>
}

interface OptionCardProps<K extends string> {
    options: readonly OptionCardItem<K>[]
    selected: K
    onSelect: (key: K) => void
    /** Each row's test ID is `<prefix>-<key>`. */
    testIDPrefix: string
}

/** A sheet's single choice: one row per option with its icon, and a check and a sunken fill on the chosen row. */
export function OptionCard<K extends string>({
    options,
    selected,
    onSelect,
    testIDPrefix,
}: OptionCardProps<K>): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card} accessibilityRole="radiogroup">
            {options.map((option, index) => (
                <Fragment key={option.key}>
                    {index > 0 ? <View style={styles.divider} /> : null}
                    <OptionRow
                        option={option}
                        selected={selected === option.key}
                        onPress={() => onSelect(option.key)}
                        testID={`${testIDPrefix}-${option.key}`}
                    />
                </Fragment>
            ))}
        </View>
    )
}

interface OptionRowProps<K extends string> {
    option: OptionCardItem<K>
    selected: boolean
    onPress: () => void
    testID: string
}

function OptionRow<K extends string>({ option, selected, onPress, testID }: OptionRowProps<K>): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { Icon } = option
    return (
        <Pressable44
            onPress={onPress}
            hitSlop={0}
            accessibilityRole="radio"
            accessibilityLabel={option.description ? `${option.label}, ${option.description}` : option.label}
            accessibilityState={{ selected }}
            pressedBackground={colors.pressed}
            style={[styles.row, selected && styles.rowSelected]}
            testID={testID}
        >
            <Icon size={iconSizes.control} color={colors.ink} />
            <View style={styles.rowText}>
                <Text style={styles.rowLabel}>{option.label}</Text>
                {option.description ? <Text style={styles.rowDescription}>{option.description}</Text> : null}
            </View>
            {selected ? <CheckIcon size={iconSizes.control} /> : null}
        </Pressable44>
    )
}

const ROW_PADDING = space[16]
const ROW_GAP = space[12]
// Dividers start under the label, past the icon, like a grouped list.
const ROW_TEXT_INSET = ROW_PADDING + iconSizes.control + ROW_GAP

const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.softCard,
        overflow: 'hidden',
    },
    divider: {
        height: StyleSheet.hairlineWidth,
        marginLeft: ROW_TEXT_INSET,
        backgroundColor: colors.rowDivider,
    },
    row: {
        minHeight: 56,
        paddingVertical: space[8],
        paddingHorizontal: ROW_PADDING,
        flexDirection: 'row',
        alignItems: 'center',
        gap: ROW_GAP,
    },
    rowSelected: {
        backgroundColor: colors.sunken,
    },
    rowText: {
        flex: 1,
        minWidth: 0,
    },
    rowLabel: {
        ...type.body,
        color: colors.ink,
    },
    rowDescription: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
