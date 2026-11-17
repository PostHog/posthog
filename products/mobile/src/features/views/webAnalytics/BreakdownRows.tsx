import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { groupThousands } from '@/model/adapters/text'
import type { WebBreakdownRow } from '@/model/views'
import { seriesColor } from '@/ui/chart/palette'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, radii, type } from '@/ui/tokens'

const VALUE_WIDTH = 64
const SECONDARY_WIDTH = 58

export function BreakdownColumns({ secondaryLabel }: { secondaryLabel: string | null }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.columns} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Text style={[styles.columnName, styles.valueColumn]}>Visitors</Text>
            {secondaryLabel ? <Text style={[styles.columnName, styles.secondaryColumn]}>{secondaryLabel}</Text> : null}
        </View>
    )
}

interface BreakdownRowsProps {
    rows: readonly WebBreakdownRow[]
    secondaryLabel: string | null
    ranked?: boolean
    isActive: (row: WebBreakdownRow) => boolean
    onPressRow: (row: WebBreakdownRow) => void
    testID: string
}

/** A tap filters the whole screen by the row's value, as a click does on the web. */
export function BreakdownRows({
    rows,
    secondaryLabel,
    ranked = false,
    isActive,
    onPressRow,
    testID,
}: BreakdownRowsProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const top = Math.max(0, ...rows.map((row) => row.value))
    const color = seriesColor(0, chartPalette)
    return (
        <View>
            {rows.map((row, index) => {
                const active = isActive(row)
                const share = top > 0 ? Math.max(0, (row.value / top) * 100) : 0
                const visitors = groupThousands(row.value)
                const secondary = row.secondary === null ? null : groupThousands(row.secondary)
                const spoken = [
                    row.label,
                    `${visitors} visitors`,
                    secondary !== null && secondaryLabel ? `${secondary} ${secondaryLabel.toLowerCase()}` : null,
                ]
                    .filter(Boolean)
                    .join(', ')
                const content = (
                    <>
                        <View style={styles.line}>
                            {ranked ? <Text style={styles.rank}>{index + 1}</Text> : null}
                            <Text
                                style={[styles.label, row.placeholder && styles.placeholder]}
                                numberOfLines={1}
                                ellipsizeMode="middle"
                            >
                                {row.label}
                            </Text>
                            <Text style={[styles.value, styles.valueColumn]} numberOfLines={1}>
                                {visitors}
                            </Text>
                            {secondaryLabel ? (
                                <Text style={[styles.secondary, styles.secondaryColumn]} numberOfLines={1}>
                                    {secondary ?? '–'}
                                </Text>
                            ) : null}
                        </View>
                        <View style={[styles.track, ranked && styles.trackRanked]}>
                            <View style={[styles.bar, { width: `${share}%`, backgroundColor: color }]} />
                        </View>
                    </>
                )
                if (!row.filter) {
                    return (
                        <View
                            key={row.key}
                            style={styles.row}
                            accessible
                            accessibilityLabel={spoken}
                            testID={`${testID}-row-${index}`}
                        >
                            {content}
                        </View>
                    )
                }
                return (
                    <Pressable44
                        key={row.key}
                        onPress={() => onPressRow(row)}
                        hitSlop={0}
                        pressedBackground={colors.sunken}
                        accessibilityLabel={spoken}
                        accessibilityState={{ selected: active }}
                        accessibilityHint={active ? 'Removes this filter.' : 'Filters web analytics by this value.'}
                        style={[styles.row, active && styles.rowActive]}
                        testID={`${testID}-row-${index}`}
                    >
                        {content}
                    </Pressable44>
                )
            })}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    columns: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    columnName: {
        ...type.meta,
        color: colors.tertiary,
        textAlign: 'right',
    },
    valueColumn: {
        width: VALUE_WIDTH,
        textAlign: 'right',
    },
    secondaryColumn: {
        width: SECONDARY_WIDTH,
        textAlign: 'right',
    },
    row: {
        minHeight: 44,
        justifyContent: 'center',
        gap: 6,
        paddingVertical: 6,
        paddingHorizontal: 6,
        marginHorizontal: -6,
        borderRadius: radii.markLarge,
    },
    rowActive: {
        backgroundColor: colors.blueHighlight,
    },
    line: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    rank: {
        width: 24,
        fontSize: 12,
        lineHeight: lineHeight(14),
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    label: {
        flex: 1,
        minWidth: 0,
        fontSize: 14,
        lineHeight: lineHeight(14),
        color: colors.ink,
    },
    placeholder: {
        fontStyle: 'italic',
        color: colors.secondary,
    },
    value: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        fontWeight: '600',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    secondary: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    track: {
        height: 6,
    },
    trackRanked: {
        marginLeft: 24,
    },
    bar: {
        height: 6,
        minWidth: 2,
        borderRadius: 3,
    },
}))
