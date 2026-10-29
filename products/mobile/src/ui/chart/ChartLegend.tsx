import { type ReactElement, useCallback, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, radii, space } from '@/ui/tokens'

import { isCompareSeries } from './chartSeries'
import { LEGEND_ALL_VISIBLE, type LegendChange, type LegendState, soloSeries, toggleSeries } from './legendState'
import { useChartSelectionScope } from './selection/ChartSelectionProvider'
import type { ChartSeries } from './types'

/** Inline legends show this many series, then "+N". */
const INLINE_MAX_ITEMS = 3

interface ChartLegendProps {
    series: ChartSeries[]
    state: LegendState
    onChange: (state: LegendState) => void
    /** `inline` shows pills for the first three series and "+N". `fullscreen` shows every series as a 44pt row. */
    variant?: 'inline' | 'fullscreen'
    /** The "+N" pill. Without it the pill is a plain count. */
    onPressMore?: () => void
    /** The paired chart's `selectionId`, so legend taps keep its tooltip open. */
    selectionId?: string
    testID?: string
}

/** Holds a legend's state for a screen. Pass `state.hiddenKeys` to the chart's `hiddenKeys`. */
export function useChartLegend(): { state: LegendState; setState: (state: LegendState) => void } {
    const [state, setState] = useState<LegendState>(LEGEND_ALL_VISIBLE)
    return { state, setState }
}

/** Tap hides or shows a series and the axis rescales. Long press shows only that series; a tap on it shows all. */
export function ChartLegend({
    series,
    state,
    onChange,
    variant = 'inline',
    onPressMore,
    selectionId,
    testID,
}: ChartLegendProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    const scope = useChartSelectionScope()
    const apply = useCallback(
        (change: LegendChange | null): void => {
            if (!change) {
                return
            }
            onChange(change.state)
            track('mobile_chart_legend_toggled', { action: change.action })
        },
        [onChange]
    )
    const rows = variant === 'fullscreen'
    const shown = rows ? series : series.slice(0, INLINE_MAX_ITEMS)
    const more = series.length - shown.length
    const markTouch = selectionId && scope ? () => scope.markTouch(selectionId) : undefined

    return (
        <View
            style={rows ? styles.rows : styles.pills}
            onTouchStart={markTouch}
            accessibilityLabel="Series. Tap to hide or show. Press and hold to show only one."
            testID={testID}
        >
            {shown.map((s, index) => {
                const visible = !state.hiddenKeys.includes(s.key)
                return (
                    <Pressable44
                        key={s.key}
                        onPress={() => apply(toggleSeries(series, state, s.key))}
                        onLongPress={() => apply(soloSeries(series, state, s.key))}
                        accessibilityRole="togglebutton"
                        accessibilityState={{ checked: visible }}
                        accessibilityLabel={s.label}
                        hitSlop={rows ? 0 : 5}
                        pressedBackground={colors.pressed}
                        style={[
                            rows ? styles.row : styles.pill,
                            rows && index > 0 ? styles.rowDivider : null,
                            !rows && !visible ? styles.pillHidden : null,
                        ]}
                        testID={testID ? `${testID}-${s.key}` : undefined}
                    >
                        <Swatch series={s} visible={visible} />
                        <Text style={[styles.label, visible ? null : styles.labelHidden]} numberOfLines={1}>
                            {s.label}
                        </Text>
                    </Pressable44>
                )
            })}
            {more > 0 ? (
                onPressMore ? (
                    <Pressable44
                        onPress={onPressMore}
                        accessibilityLabel={`Show all ${series.length} series`}
                        hitSlop={5}
                        pressedBackground={colors.pressed}
                        style={styles.pill}
                    >
                        <Text style={styles.label}>+{more}</Text>
                    </Pressable44>
                ) : (
                    <View style={styles.pill}>
                        <Text style={styles.label}>+{more}</Text>
                    </View>
                )
            ) : null}
        </View>
    )
}

const DASH_SEGMENTS = [0, 1, 2]

function Swatch({ series, visible }: { series: ChartSeries; visible: boolean }): ReactElement {
    const { colors, previousPeriodColor } = useTheme()
    const styles = useStyles()
    if (isCompareSeries(series)) {
        // iOS draws a dashed border only when all four sides share one width, so a top-only dashed border is blank.
        // Three short segments draw the same dashed line on every platform.
        const color = visible ? previousPeriodColor : colors.border
        return (
            <View style={styles.dash}>
                {DASH_SEGMENTS.map((segment) => (
                    <View key={segment} style={[styles.dashSegment, { backgroundColor: color }]} />
                ))}
            </View>
        )
    }
    return <View style={[styles.swatch, visible ? { backgroundColor: series.color } : styles.swatchHidden]} />
}

const PILL_HEIGHT = 34

const useStyles = createStyles(({ colors }) => ({
    pills: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: space[6],
    },
    pill: {
        height: PILL_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: space[8],
        paddingHorizontal: space[12],
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        maxWidth: '100%',
    },
    pillHidden: {
        borderStyle: 'dashed',
    },
    rows: {
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.card,
        overflow: 'hidden',
        backgroundColor: colors.surface,
    },
    row: {
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: space[8],
        paddingHorizontal: space[12],
    },
    rowDivider: {
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    label: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        fontWeight: '600',
        flexShrink: 1,
        color: colors.ink,
    },
    labelHidden: {
        color: colors.tertiary,
    },
    swatch: {
        width: 10,
        height: 10,
        borderRadius: 3,
    },
    swatchHidden: {
        borderWidth: 1.5,
        borderColor: colors.disabled,
    },
    dash: {
        width: 14,
        height: 2,
        flexDirection: 'row',
        justifyContent: 'space-between',
    },
    dashSegment: {
        width: 4,
        height: 2,
        borderRadius: 1,
    },
}))
