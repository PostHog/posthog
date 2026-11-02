import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

export interface HandoffOptionRow {
    key: string
    label: string
    value: string
    detail?: string
    onPress: () => void
    testID: string
}

interface HandoffOptionRowsProps {
    rows: HandoffOptionRow[]
    disabled: boolean
}

export function HandoffOptionRows({ rows, disabled }: HandoffOptionRowsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.group}>
            {rows.map((row, index) => (
                <Pressable44
                    key={row.key}
                    onPress={row.onPress}
                    disabled={disabled}
                    accessibilityLabel={`${row.label}: ${row.value}`}
                    accessibilityHint={row.detail}
                    pressedBackground={colors.sunken}
                    style={[styles.row, index > 0 && styles.divided]}
                    testID={row.testID}
                >
                    <Text style={styles.label}>{row.label}</Text>
                    <View style={styles.values}>
                        <Text style={styles.value} numberOfLines={1}>
                            {row.value}
                        </Text>
                        {row.detail ? (
                            <Text style={styles.detail} numberOfLines={1}>
                                {row.detail}
                            </Text>
                        ) : null}
                    </View>
                    <ChevronRightIcon size={iconSizes.small} color={colors.tertiary} />
                </Pressable44>
            ))}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    group: {
        marginTop: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 48,
        paddingVertical: 6,
        paddingHorizontal: 12,
    },
    divided: {
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    label: {
        ...type.bodySmall,
        color: colors.muted,
    },
    values: {
        flex: 1,
        minWidth: 0,
        alignItems: 'flex-end',
    },
    value: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    detail: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
