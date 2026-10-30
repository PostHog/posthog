import { type ReactElement, useCallback } from 'react'
import { Text, View } from 'react-native'

import { groupThousands, plural } from '@/model/adapters/text'
import type { RankingView } from '@/model/views'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, radii, type } from '@/ui/tokens'

import { useItemChartAccessibility } from './accessibility/useChartAccessibility'
import { seriesColor } from './palette'
import { useItemSelection } from './selection/useItemSelection'
import type { ChartAccessibilityAction, ChartTrackingContext } from './types'

interface BarListProps {
    ranking: RankingView
    /** The insight's name, for the spoken summary. */
    label: string
    formatValue: (value: number) => string
    /** Rows to show before "+N more". Shows every row when left out. */
    maxRows?: number
    /** The "+N more" row. Without it the row is plain text. */
    onPressMore?: () => void
    selectionId?: string
    trackingContext?: ChartTrackingContext
    accessibilityActions?: readonly ChartAccessibilityAction[]
    testID?: string
}

function ordinal(rank: number): string {
    const tens = rank % 100
    if (tens >= 11 && tens <= 13) {
        return `${rank}th`
    }
    return `${rank}${['th', 'st', 'nd', 'rd'][rank % 10] ?? 'th'}`
}

/**
 * Breakdown values or series ranked as horizontal bars, highest first. Each row is a label, its value and a bar as a
 * share of the top value. A tap on a row shows its share of the total, or its rank when the rows do not add up.
 */
export function BarList({
    ranking,
    label,
    formatValue,
    maxRows,
    onPressMore,
    selectionId,
    trackingContext,
    accessibilityActions,
    testID,
}: BarListProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const { rows, total } = ranking
    const shown = maxRows === undefined ? rows : rows.slice(0, maxRows)
    const more = rows.length - shown.length
    const selection = useItemSelection({
        selectionId,
        kind: 'bar_list',
        seriesCount: rows.length,
        dataKey: ranking,
        trackingContext,
    })
    const detail = useCallback(
        (index: number): string => {
            const row = rows[index]
            if (!row) {
                return ''
            }
            if (total !== null && total > 0) {
                return `${groupThousands((row.value / total) * 100, 1)}% of the total`
            }
            return `${ordinal(index + 1)} of ${rows.length}`
        },
        [rows, total]
    )
    const describe = useCallback(
        (index: number): string => {
            const row = rows[index]
            return row ? `${row.label}: ${formatValue(row.value)}, ${detail(index)}.` : ''
        },
        [rows, formatValue, detail]
    )
    const top = rows[0]
    const moreAction: ChartAccessibilityAction[] =
        more > 0 && onPressMore ? [{ name: 'showAll', label: `Show all ${rows.length}`, onAction: onPressMore }] : []
    const a11y = useItemChartAccessibility({
        summary: [
            `${label}, ${plural(rows.length, 'value')} ranked`,
            top ? `Highest ${top.label}, ${formatValue(top.value)}` : null,
        ]
            .filter(Boolean)
            .join('. '),
        count: shown.length,
        selected: selection.selected,
        describe,
        select: (index) => selection.select(index, 'accessibility'),
        clear: () => selection.clear('back'),
        hint: 'Swipe up or down to move between values.',
        actions: [...moreAction, ...(accessibilityActions ?? [])],
    })

    if (rows.length === 0) {
        return (
            <Text style={styles.empty} testID={testID}>
                No values in this date range.
            </Text>
        )
    }
    const max = Math.max(...rows.map((row) => row.value), 0)
    const color = seriesColor(0, chartPalette)
    return (
        <View ref={selection.viewRef} onTouchStart={selection.onTouchStart} testID={testID} {...a11y}>
            {shown.map((row, index) => {
                const selected = selection.selected === index
                const width = max > 0 ? Math.max(0, (row.value / max) * 100) : 0
                return (
                    <Pressable44
                        key={row.key}
                        onPress={() => selection.toggle(index)}
                        hitSlop={0}
                        pressedBackground={colors.sunken}
                        accessible={false}
                        style={[styles.row, selected && styles.rowSelected]}
                        testID={testID ? `${testID}-row-${index}` : undefined}
                    >
                        <View style={styles.line}>
                            <Text style={styles.label} numberOfLines={2}>
                                {row.label}
                            </Text>
                            <Text style={styles.value}>{formatValue(row.value)}</Text>
                        </View>
                        <View style={[styles.bar, { width: `${width}%`, backgroundColor: color }]} />
                        {selected ? <Text style={styles.detail}>{detail(index)}</Text> : null}
                    </Pressable44>
                )
            })}
            {more > 0 ? (
                onPressMore ? (
                    <Pressable44
                        onPress={onPressMore}
                        hitSlop={0}
                        accessible={false}
                        pressedBackground={colors.sunken}
                        style={styles.more}
                        testID={testID ? `${testID}-more` : undefined}
                    >
                        <Text style={styles.moreText}>+{more} more</Text>
                    </Pressable44>
                ) : (
                    <Text style={[styles.moreText, styles.more]}>+{more} more</Text>
                )
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        minHeight: 44,
        justifyContent: 'center',
        gap: 5,
        paddingVertical: 5,
        paddingHorizontal: 6,
        marginHorizontal: -6,
        borderRadius: radii.markLarge,
    },
    rowSelected: {
        backgroundColor: colors.blueHighlight,
    },
    line: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 10,
    },
    label: {
        flex: 1,
        fontSize: 14,
        lineHeight: lineHeight(14),
        color: colors.ink,
    },
    value: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        fontWeight: '600',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    bar: {
        height: 8,
        minWidth: 2,
        borderTopRightRadius: 4,
        borderBottomRightRadius: 4,
    },
    detail: {
        fontSize: 12,
        lineHeight: lineHeight(12),
        color: colors.secondary,
        fontVariant: ['tabular-nums'],
    },
    more: {
        minHeight: 36,
        justifyContent: 'center',
        paddingHorizontal: 6,
        marginHorizontal: -6,
        borderRadius: radii.markLarge,
    },
    moreText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.secondary,
    },
    empty: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
}))
