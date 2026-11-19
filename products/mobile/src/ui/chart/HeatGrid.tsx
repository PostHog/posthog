import { type ReactElement, useCallback, useMemo, useState } from 'react'
import { type GestureResponderEvent, type LayoutChangeEvent, Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, type } from '@/ui/tokens'

import { useItemChartAccessibility } from './accessibility/useChartAccessibility'
import { seriesColor } from './palette'
import { useItemSelection } from './selection/useItemSelection'

const ROW_LABEL_WIDTH = 34
const CELL_HEIGHT = 16
const CELL_GAP = 2

interface HeatGridProps {
    cells: readonly (readonly number[])[]
    rowLabels: readonly string[]
    /** Columns that get a label under the grid, with the label, such as `[0, '00:00']`. */
    columnMarks: readonly (readonly [number, string])[]
    /** One cell as a sentence, such as "Tue 14:00 · 1,204 visitors". It is the callout and the spoken value. */
    describe: (row: number, column: number, value: number) => string
    label: string
    selectionId?: string
    testID?: string
}

function channel(hex: string, offset: number): number {
    return Number.parseInt(hex.slice(offset, offset + 2), 16)
}

function shade(share: number, base: string, card: string): string {
    const mix = 0.05 + Math.max(0, Math.min(1, share)) * 0.85
    const blend = (offset: number): number =>
        Math.round(channel(card, offset) + (channel(base, offset) - channel(card, offset)) * mix)
    return `rgb(${blend(1)}, ${blend(3)}, ${blend(5)})`
}

/** The cells are too small for their own touch targets, so one press area maps a tap to its cell. */
export function HeatGrid({
    cells,
    rowLabels,
    columnMarks,
    describe,
    label,
    selectionId,
    testID,
}: HeatGridProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const base = seriesColor(0, chartPalette)
    const columns = cells[0]?.length ?? 0
    const count = cells.length * columns
    const [width, setWidth] = useState(0)
    // No tracking context: the chart events name no heat grid kind, so the grid sends none.
    const selection = useItemSelection({ selectionId, kind: 'table', seriesCount: 1, dataKey: cells })
    const { max, busiest } = useMemo(() => {
        let best = -1
        let top = 0
        cells.forEach((row, rowIndex) => {
            row.forEach((value, column) => {
                if (value > top) {
                    top = value
                    best = rowIndex * columns + column
                }
            })
        })
        return { max: top, busiest: best }
    }, [cells, columns])
    const sentence = useCallback(
        (index: number): string => {
            const row = Math.floor(index / Math.max(1, columns))
            const column = index % Math.max(1, columns)
            return describe(row, column, cells[row]?.[column] ?? 0)
        },
        [cells, columns, describe]
    )
    const a11y = useItemChartAccessibility({
        summary: [label, busiest >= 0 ? `Busiest ${sentence(busiest)}` : null].filter(Boolean).join('. '),
        count,
        selected: selection.selected,
        describe: sentence,
        select: (index) => selection.select(index, 'accessibility'),
        clear: () => selection.clear('back'),
        hint: 'Swipe up or down to move between cells.',
    })
    const onLayout = useCallback((event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width), [])
    const onPress = (event: GestureResponderEvent): void => {
        if (width <= 0 || columns === 0) {
            return
        }
        const { locationX, locationY } = event.nativeEvent
        const column = Math.min(columns - 1, Math.max(0, Math.floor((locationX / width) * columns)))
        const row = Math.min(cells.length - 1, Math.max(0, Math.floor(locationY / (CELL_HEIGHT + CELL_GAP))))
        selection.toggle(row * columns + column)
    }
    const selectedRow = selection.selected >= 0 ? Math.floor(selection.selected / columns) : -1
    const selectedColumn = selection.selected >= 0 ? selection.selected % columns : -1
    const callout =
        selection.selected >= 0 ? sentence(selection.selected) : busiest >= 0 ? `Busiest: ${sentence(busiest)}` : null

    return (
        <View ref={selection.viewRef} onTouchStart={selection.onTouchStart} testID={testID} {...a11y}>
            <View style={styles.body}>
                <View style={styles.rowLabels}>
                    {rowLabels.map((rowLabel, index) => (
                        <Text
                            key={rowLabel}
                            style={[styles.rowLabel, index === selectedRow && styles.rowLabelSelected]}
                            numberOfLines={1}
                        >
                            {rowLabel}
                        </Text>
                    ))}
                </View>
                <View style={styles.grid} onLayout={onLayout}>
                    <Pressable44
                        onPress={onPress}
                        hitSlop={0}
                        accessible={false}
                        testID={testID ? `${testID}-cells` : undefined}
                    >
                        {cells.map((row, rowIndex) => (
                            // biome-ignore lint/suspicious/noArrayIndexKey: rows are fixed positions, such as weekdays.
                            <View key={rowIndex} style={styles.cellRow} pointerEvents="none">
                                {row.map((value, column) => (
                                    <View
                                        // biome-ignore lint/suspicious/noArrayIndexKey: columns are fixed positions.
                                        key={column}
                                        style={[
                                            styles.cell,
                                            { backgroundColor: shade(max > 0 ? value / max : 0, base, colors.surface) },
                                            rowIndex === selectedRow && column === selectedColumn && styles.cellActive,
                                        ]}
                                    />
                                ))}
                            </View>
                        ))}
                    </Pressable44>
                    <View style={styles.marks}>
                        {columnMarks.map(([column, mark]) => (
                            <Text
                                key={column}
                                style={[styles.mark, { left: `${(column / Math.max(1, columns)) * 100}%` }]}
                                numberOfLines={1}
                            >
                                {mark}
                            </Text>
                        ))}
                    </View>
                </View>
            </View>
            {callout ? (
                <Text style={styles.callout} testID={testID ? `${testID}-callout` : undefined}>
                    {callout}
                </Text>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        flexDirection: 'row',
    },
    rowLabels: {
        width: ROW_LABEL_WIDTH,
    },
    rowLabel: {
        height: CELL_HEIGHT + CELL_GAP,
        fontSize: 11,
        lineHeight: CELL_HEIGHT,
        color: colors.tertiary,
    },
    rowLabelSelected: {
        color: colors.ink,
        fontWeight: '700',
    },
    grid: {
        flex: 1,
        minWidth: 0,
    },
    cellRow: {
        flexDirection: 'row',
        height: CELL_HEIGHT + CELL_GAP,
    },
    cell: {
        flex: 1,
        height: CELL_HEIGHT,
        marginRight: 1,
        borderRadius: 2,
    },
    cellActive: {
        borderWidth: 1.5,
        borderColor: colors.ink,
    },
    marks: {
        height: 18,
        marginTop: 2,
    },
    mark: {
        position: 'absolute',
        top: 0,
        fontSize: 11,
        lineHeight: lineHeight(11),
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    callout: {
        ...type.meta,
        marginTop: 8,
        color: colors.secondary,
        fontVariant: ['tabular-nums'],
    },
}))
