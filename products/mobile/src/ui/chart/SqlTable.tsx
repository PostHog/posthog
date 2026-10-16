import { memo, type ReactElement, useCallback, useMemo, useState } from 'react'
import {
    type LayoutChangeEvent,
    ScrollView,
    type StyleProp,
    StyleSheet,
    Text,
    type TextStyle,
    View,
    type ViewStyle,
} from 'react-native'

import { groupThousands, plural } from '@/model/adapters/text'
import type { SqlColumnView, SqlTableView } from '@/model/views'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, lineHeight, radii, type } from '@/ui/tokens'

import { useItemChartAccessibility } from './accessibility/useChartAccessibility'
import { useItemSelection } from './selection/useItemSelection'
import { formatSqlCell, SQL_TABLE_MAX_ROWS, sqlRowsText } from './sqlCellFormat'
import type { ChartAccessibilityAction, ChartTrackingContext } from './types'

const HEAD_HEIGHT = 30
// Fixed, because the pinned column and the scrolling columns draw each row in separate stacks that must line up.
const ROW_HEIGHT = 36

interface SqlTableProps {
    table: SqlTableView
    /** The insight's name, for the spoken summary. */
    label: string
    /** Rows to show before "+N more". Left out, it shows up to `SQL_TABLE_MAX_ROWS` and says so under the rows. */
    maxRows?: number
    /** The "+N more" row. Without it the row is plain text. */
    onPressMore?: () => void
    selectionId?: string
    trackingContext?: ChartTrackingContext
    accessibilityActions?: readonly ChartAccessibilityAction[]
    testID?: string
}

function columnWidth(column: SqlColumnView): number {
    if (column.isNumerical) {
        return 72
    }
    if (column.scalar === 'DATETIME') {
        return 128
    }
    return 96
}

function alignRight(column: SqlColumnView): boolean {
    return column.isNumerical || column.isDate
}

type Cell = string | null

/** A cell's box and its text styles, built once per column layout instead of once per cell. */
interface ColumnStyle {
    box: StyleProp<ViewStyle>
    text: StyleProp<TextStyle>
    empty: StyleProp<TextStyle>
    head: StyleProp<TextStyle>
}

function columnStyles(part: readonly SqlColumnView[], fixed: boolean, growText: boolean): ColumnStyle[] {
    return part.map((column) => {
        const right = alignRight(column)
        const box: ViewStyle = fixed
            ? { width: columnWidth(column) }
            : // Text columns take the room left when the columns fit; numbers and dates stay at their minimum width.
              { flexBasis: columnWidth(column), flexGrow: growText && right ? 0 : 1, flexShrink: 0 }
        const text = right ? [styles.cellText, styles.right, styles.numeric] : [styles.cellText]
        return {
            box: [box, styles.cell],
            text,
            empty: [...text, styles.null],
            head: right ? [styles.headText, styles.right] : styles.headText,
        }
    })
}

interface SqlRowProps {
    index: number
    cells: readonly Cell[]
    columnStyles: readonly ColumnStyle[]
    selected: boolean
    onToggle: (index: number) => void
    testID?: string
}

// Memoized, so a tap re-renders only the rows whose selection changed, not every drawn row.
const SqlRow = memo(function SqlRow({
    index,
    cells,
    columnStyles: layout,
    selected,
    onToggle,
    testID,
}: SqlRowProps): ReactElement {
    return (
        <Pressable44
            onPress={() => onToggle(index)}
            hitSlop={0}
            accessible={false}
            style={selected ? [styles.row, styles.rowSelected] : styles.row}
            testID={testID}
        >
            {layout.map((style, at) => {
                const text = cells[at] ?? null
                return (
                    // biome-ignore lint/suspicious/noArrayIndexKey: columns have a fixed order within a table.
                    <View key={at} style={style.box}>
                        <Text style={text === null ? style.empty : style.text} numberOfLines={1}>
                            {text ?? '–'}
                        </Text>
                    </View>
                )
            })}
        </Pressable44>
    )
})

/**
 * The rows of a SQL insight in the server's order. Columns share the width when they fit. When they do not, the first
 * column stays put and the others scroll sideways. A tap on a row highlights it across both parts.
 */
export function SqlTable({
    table,
    label,
    maxRows,
    onPressMore,
    selectionId,
    trackingContext,
    accessibilityActions,
    testID,
}: SqlTableProps): ReactElement {
    const { columns, rows, hasMore } = table
    const limit = Math.min(rows.length, maxRows ?? SQL_TABLE_MAX_ROWS)
    const more = rows.length - limit
    // Only a tile has "+N more". A screen cut at the drawing cap says so in the footer and its caption.
    const capped = maxRows === undefined && more > 0
    const [width, setWidth] = useState(0)
    const shown = useMemo(() => {
        const now = Date.now()
        return rows
            .slice(0, limit)
            .map((row) => columns.map((column, index) => formatSqlCell(row[index] ?? null, column, now)))
    }, [rows, columns, limit])
    const totalWidth = columns.reduce((sum, column) => sum + columnWidth(column), 0)
    const pinned = columns.length > 1 && width > 0 && totalWidth > width
    const layout = useMemo(() => {
        const growText = columns.some((column) => !alignRight(column))
        return {
            pinned: columnStyles(columns.slice(0, 1), true, growText),
            scrolling: columnStyles(pinned ? columns.slice(1) : columns, pinned, growText),
        }
    }, [columns, pinned])
    // Each row's cells split once per layout, so the memoized rows get the same arrays on every render.
    const parts = useMemo(
        () => shown.map((row) => (pinned ? { pinned: row.slice(0, 1), scrolling: row.slice(1) } : { scrolling: row })),
        [shown, pinned]
    )
    const selection = useItemSelection({
        selectionId,
        kind: 'table',
        seriesCount: columns.length,
        dataKey: table,
        trackingContext,
    })
    const describe = useCallback(
        (index: number): string =>
            columns.map((column, at) => `${column.name} ${shown[index]?.[at] ?? 'empty'}`).join(', '),
        [columns, shown]
    )
    const moreAction: ChartAccessibilityAction[] =
        more > 0 && onPressMore ? [{ name: 'showAll', label: `Show all ${rows.length}`, onAction: onPressMore }] : []
    const drawnText = sqlRowsText(table, limit)
    const spokenRows = `${drawnText.charAt(0).toLowerCase()}${drawnText.slice(1)}`
    const columnNames = columns.map((column) => column.name).join(', ')
    const a11y = useItemChartAccessibility({
        summary: `${label}. Table, ${spokenRows}, ${plural(columns.length, 'column')}: ${columnNames}`,
        count: shown.length,
        selected: selection.selected,
        describe,
        select: (index) => selection.select(index, 'accessibility'),
        clear: () => selection.clear('back'),
        hint: 'Swipe up or down to move between rows.',
        actions: [...moreAction, ...(accessibilityActions ?? [])],
    })
    const onLayout = useCallback((event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width), [])

    if (rows.length === 0) {
        return (
            <Text style={styles.empty} testID={testID}>
                No rows
            </Text>
        )
    }

    const first = columns[0]
    const scrolling = pinned ? columns.slice(1) : columns
    // Inside a horizontal scroll view the rows size to their longest text, so the table takes the container's width
    // when the columns fit, and the scrolling columns keep their minimum widths when they do not.
    const tableWidth = pinned || width === 0 ? undefined : width
    const rowTestID = (index: number, suffix: string): string | undefined =>
        testID ? `${testID}-row-${index}${suffix}` : undefined
    const head = (column: SqlColumnView, style: ColumnStyle | undefined, key: string): ReactElement => (
        <View key={key} style={style?.box}>
            <Text style={style?.head} numberOfLines={1}>
                {column.name}
            </Text>
        </View>
    )

    return (
        <View
            ref={selection.viewRef}
            onTouchStart={selection.onTouchStart}
            onLayout={onLayout}
            testID={testID}
            {...a11y}
        >
            <View style={styles.grid}>
                {pinned && first ? (
                    <View style={[styles.pinned, { width: columnWidth(first) }]}>
                        <View style={styles.headRow}>{head(first, layout.pinned[0], 'pinned')}</View>
                        {parts.map((part, index) => (
                            <SqlRow
                                // biome-ignore lint/suspicious/noArrayIndexKey: rows keep the server's order.
                                key={index}
                                index={index}
                                cells={part.pinned ?? []}
                                columnStyles={layout.pinned}
                                selected={selection.selected === index}
                                onToggle={selection.toggle}
                                testID={rowTestID(index, '-pinned')}
                            />
                        ))}
                    </View>
                ) : null}
                <ScrollView
                    horizontal
                    scrollEnabled={pinned}
                    showsHorizontalScrollIndicator={false}
                    style={styles.scroll}
                    contentContainerStyle={styles.scrollContent}
                    testID={testID ? `${testID}-scroll` : undefined}
                >
                    <View style={[styles.table, tableWidth !== undefined && { width: tableWidth }]}>
                        <View style={styles.headRow}>
                            {scrolling.map((column, at) => head(column, layout.scrolling[at], `${at}`))}
                        </View>
                        {parts.map((part, index) => (
                            <SqlRow
                                // biome-ignore lint/suspicious/noArrayIndexKey: rows keep the server's order.
                                key={index}
                                index={index}
                                cells={part.scrolling}
                                columnStyles={layout.scrolling}
                                selected={selection.selected === index}
                                onToggle={selection.toggle}
                                testID={rowTestID(index, '')}
                            />
                        ))}
                    </View>
                </ScrollView>
            </View>
            {more > 0 && !capped ? (
                onPressMore ? (
                    <Pressable44
                        onPress={onPressMore}
                        hitSlop={0}
                        accessible={false}
                        pressedBackground={colors.sunken}
                        style={styles.more}
                        testID={testID ? `${testID}-more` : undefined}
                    >
                        <Text style={styles.moreText}>+{groupThousands(more)} more</Text>
                    </Pressable44>
                ) : (
                    <Text style={[styles.moreText, styles.more]}>+{groupThousands(more)} more</Text>
                )
            ) : capped || hasMore ? (
                <Text style={styles.footer} testID={testID ? `${testID}-has-more` : undefined}>
                    {drawnText}
                </Text>
            ) : null}
        </View>
    )
}

const styles = StyleSheet.create({
    grid: {
        flexDirection: 'row',
    },
    pinned: {
        borderRightWidth: StyleSheet.hairlineWidth,
        borderRightColor: colors.hairline,
    },
    scroll: {
        flex: 1,
    },
    scrollContent: {
        flexGrow: 1,
    },
    table: {
        flexGrow: 1,
    },
    headRow: {
        flexDirection: 'row',
        height: HEAD_HEIGHT,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: colors.border,
    },
    row: {
        flexDirection: 'row',
        height: ROW_HEIGHT,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: colors.rowDivider,
    },
    rowSelected: {
        backgroundColor: colors.blueHighlight,
    },
    cell: {
        justifyContent: 'center',
        paddingHorizontal: 6,
    },
    headText: {
        fontSize: 11,
        lineHeight: lineHeight(11),
        fontWeight: '600',
        color: colors.tertiary,
    },
    cellText: {
        fontSize: 13,
        lineHeight: lineHeight(13),
        color: colors.ink,
    },
    right: {
        textAlign: 'right',
    },
    numeric: {
        fontVariant: ['tabular-nums'],
    },
    null: {
        color: colors.tertiary,
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
    footer: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 10,
    },
    empty: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
})
